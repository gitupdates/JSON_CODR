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
