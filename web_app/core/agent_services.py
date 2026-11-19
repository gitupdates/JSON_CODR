from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from pydantic import ValidationError

from web_app.core.adapters import CapabilityCall
from web_app.core.context_service import ContextBundle
from web_app.core.contracts import (
    CriterionStatus,
    EvidenceRef,
    GoalSpec,
    TaskCommand,
    TaskRecord,
    VerificationReport,
)
from web_app.core.project_intelligence import ProjectReader


class ProjectContextResolver:
    def __init__(self, project_roots: Mapping[str, str | Path]) -> None:
        self._roots = {project_id: Path(root).resolve() for project_id, root in project_roots.items()}

    def resolve(self, command: TaskCommand) -> tuple[ProjectReader, str]:
        root = self._roots.get(command.project_id)
        if root is None:
            raise KeyError("project is not registered")
        target = command.payload.get("target_path", ".")
        return ProjectReader(root), target if isinstance(target, str) else "."


class InferencePlanner:
    def __init__(self, generate: Callable[[str, str], Awaitable[str]], *, model: str) -> None:
        self._generate = generate
        self._model = model

    async def plan(self, context: ContextBundle) -> CapabilityCall | None:
        project_root = self._project_root(context)
        prompt = (
            "Act as a local coding planner. Return one capability call as a JSON object with "
            "capability_id, operation, target_path when needed, and arguments. Return "
            '{"done":true} only when the supplied evidence proves the task is complete. '
            "Do not include markdown or prose.\n\nCONTEXT:\n" + context.text
        )
        raw = await self._generate(self._model, prompt)
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("planner must return valid capability JSON") from error
        if not isinstance(value, dict):
            raise ValueError("planner must return valid capability JSON")
        if value.get("done") is True:
            return None
        try:
            return CapabilityCall.model_validate({**value, "project_root": project_root})
        except ValidationError as error:
            raise ValueError("planner must return valid capability JSON") from error

    @staticmethod
    def _project_root(context: ContextBundle) -> str:
        for source in reversed(context.sources):
            if source.kind != "project_snapshot":
                continue
            try:
                value = json.loads(source.content)
            except json.JSONDecodeError:
                continue
            root = value.get("project_root") if isinstance(value, dict) else None
            if isinstance(root, str) and root:
                return root
        raise ValueError("trusted project snapshot is unavailable")


class EventEvidenceVerifier:
    async def verify(
        self, goal: GoalSpec, task: TaskRecord, context: ContextBundle
    ) -> VerificationReport:
        fingerprint = self._project_fingerprint(context)
        completed = [event for event in task.events if event.event_type == "agent.action_completed"]
        passed = bool(completed)
        results = {
            criterion.criterion_id: CriterionStatus.passed if passed else CriterionStatus.failed
            for criterion in goal.criteria
        }
        evidence = ()
        if passed:
            source = completed[-1]
            child = source.payload.get("child_task_id", "unknown")
            observed_at = datetime.now(UTC)
            evidence = tuple(
                EvidenceRef(
                    evidence_id=str(uuid7()), task_id=task.task_id, project_id=task.project_id,
                    goal_id=goal.goal_id, goal_revision=goal.revision,
                    criterion_id=criterion.criterion_id,
                    source_ref=f"task:{task.task_id}:child:{child}",
                    project_fingerprint=fingerprint, observed_at=observed_at,
                )
                for criterion in goal.criteria
            )
        return VerificationReport(
            report_id=str(uuid7()), task_id=task.task_id, project_id=task.project_id,
            goal_id=goal.goal_id, goal_revision=goal.revision,
            expected_criterion_ids=tuple(item.criterion_id for item in goal.criteria),
            results=results, evidence=evidence, verified_at=datetime.now(UTC),
        )

    @staticmethod
    def _project_fingerprint(context: ContextBundle) -> str:
        for source in reversed(context.sources):
            if source.kind != "project_snapshot":
                continue
            try:
                value = json.loads(source.content)
            except json.JSONDecodeError:
                continue
            fingerprint = value.get("project_fingerprint") if isinstance(value, dict) else None
            if isinstance(fingerprint, str) and fingerprint:
                return fingerprint
        raise ValueError("trusted project fingerprint is unavailable")
