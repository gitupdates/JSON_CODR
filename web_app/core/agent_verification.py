from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import (
    FrozenContract,
    GoalSpec,
    TaskCommand,
    TaskEvent,
    TaskEventDraft,
    VerificationReport,
)
from web_app.models import TaskDelivery


class StaleEvidence(RuntimeError):
    pass


class NormalizedFailure(FrozenContract):
    code: str
    safe_summary: str
    signature: str


class RepairDecision(FrozenContract):
    allowed: bool
    attempt: int = Field(ge=0)
    reason: str


class EvidenceResolver:
    def validate(
        self,
        report: VerificationReport,
        goal: GoalSpec,
        task: TaskCommand,
        *,
        current_project_fingerprint: str,
    ) -> VerificationReport:
        if (
            report.task_id != task.task_id
            or report.project_id != task.project_id
            or report.goal_id != goal.goal_id
            or report.goal_revision != goal.revision
        ):
            raise StaleEvidence("verification report belongs to another task, project, or goal revision")
        expected = {criterion.criterion_id for criterion in goal.criteria}
        if set(report.results) != expected:
            raise StaleEvidence("verification report does not cover the current goal criteria")
        if any(item.project_fingerprint != current_project_fingerprint for item in report.evidence):
            raise StaleEvidence("verification evidence predates the current project state")
        return report


class FailureNormalizer:
    @staticmethod
    def normalize(
        *,
        capability_id: str,
        operation: str,
        status: str,
        events: Iterable[TaskEvent | TaskEventDraft],
    ) -> NormalizedFailure:
        code = "capability_failed"
        for event in reversed(tuple(events)):
            value = event.payload.get("code")
            if isinstance(value, str) and value:
                code = value[:128]
                break
        material = {
            "capability_id": capability_id,
            "operation": operation,
            "status": status,
            "code": code,
        }
        return NormalizedFailure(
            code=code,
            safe_summary=f"{capability_id}:{operation} ended with {status} ({code})",
            signature=canonical_digest(material),
        )


class RepairLoopGuard:
    def __init__(self, max_attempts_per_criterion: int = 3) -> None:
        if max_attempts_per_criterion < 1:
            raise ValueError("repair budget must allow at least one attempt")
        self.max_attempts_per_criterion = max_attempts_per_criterion
        self._attempts: dict[str, int] = {}
        self._seen: set[tuple[str, str, str, str]] = set()

    def record(
        self,
        criterion_id: str,
        failure_signature: str,
        call_digest: str,
        project_fingerprint: str,
    ) -> RepairDecision:
        attempt = self._attempts.get(criterion_id, 0)
        identity = (criterion_id, failure_signature, call_digest, project_fingerprint)
        if identity in self._seen:
            return RepairDecision(allowed=False, attempt=attempt, reason="unchanged repair loop")
        if attempt >= self.max_attempts_per_criterion:
            return RepairDecision(allowed=False, attempt=attempt, reason="repair budget exhausted")
        attempt += 1
        self._attempts[criterion_id] = attempt
        self._seen.add(identity)
        return RepairDecision(allowed=True, attempt=attempt, reason="repair attempt allowed")


def build_task_delivery(task_id: str, tasks, artifacts) -> TaskDelivery:
    record = tasks.get(task_id)
    plans = tasks.plans(task_id)
    plan = plans[-1] if plans else None
    binding = next(
        (event for event in reversed(record.events) if event.event_type == "agent.plan_context_bound"),
        None,
    )
    completed = [event for event in record.events if event.event_type == "agent.action_completed"]
    changed_paths = tuple(sorted({
        path
        for event in completed
        for path in event.payload.get("changed_paths", [])
        if isinstance(path, str)
    }))
    child_results = tuple({
        "task_id": child.task_id,
        "status": child.status.value,
        "parent_task_id": child.parent_task_id,
    } for child in tasks.children(task_id))
    verification_event = next(
        (event for event in reversed(record.events) if event.event_type == "agent.verification_completed"),
        None,
    )
    warnings = []
    if verification_event is None:
        warnings.append("Verification has not completed")
    artifact_refs = tuple({
        "artifact_id": item["artifact_id"],
        "media_type": item["media_type"],
        "size": item["size"],
        "download_url": f"/api/tasks/{task_id}/artifacts/{item['artifact_id']}",
    } for item in artifacts.export_manifest(task_id))
    phase = tasks.phase(task_id)
    paused = phase.value in {"plan_review", "blocked"}
    return TaskDelivery(
        task_id=task_id,
        executed_plan_id=None if plan is None else plan.plan_id,
        executed_plan_revision=None if plan is None else plan.revision,
        executed_plan_digest=None if plan is None else plan.canonical_digest,
        route_disclosure={} if binding is None else {
            "policy_digest": binding.payload.get("policy_digest"),
            "project_fingerprint": binding.payload.get("project_fingerprint"),
        },
        changed_paths=changed_paths,
        child_results=child_results,
        verification={} if verification_event is None else dict(verification_event.payload),
        warnings=tuple(warnings),
        recovery_controls={"apply_policy": paused, "refresh_baseline": paused},
        artifacts=artifact_refs,
    )
