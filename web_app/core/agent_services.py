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
from web_app.core.project_registry import ProjectRegistry


def planner_output_schema(capability_ids: tuple[str, ...] = ()) -> dict:
    capability_schema: dict[str, object] = {"type": "string", "minLength": 1}
    if capability_ids:
        capability_schema["enum"] = list(capability_ids)
    return {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "capability_id": capability_schema,
            "operation": {"type": "string", "minLength": 1},
            "target_path": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["done", "capability_id", "operation", "target_path", "arguments"],
    }


def select_agent_planner_model(config: Mapping[str, object]) -> str:
    primary = str(config["model"])
    fallback = str(config.get("tool_fallback_model") or "")
    verified = config.get("verified_tool_models")
    if fallback and isinstance(verified, (list, tuple)) and fallback in verified:
        return fallback
    return primary


class ProjectContextResolver:
    def __init__(self, project_roots: Mapping[str, str | Path] | ProjectRegistry) -> None:
        self._registry = project_roots if isinstance(project_roots, ProjectRegistry) else None
        self._roots = (
            {} if self._registry is not None
            else {project_id: Path(root).resolve() for project_id, root in project_roots.items()}
        )

    def resolve(self, command: TaskCommand) -> tuple[ProjectReader, str]:
        if self._registry is not None:
            root = self._registry.resolve(command.project_id)
        else:
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
        current_goal = next(
            (
                source.content for source in reversed(context.sources)
                if source.event_type == "agent.goal_registered"
            ),
            "",
        )
        prompt = (
            "Act as a local coding planner. Return one capability call as a JSON object with "
            "capability_id, operation, target_path when needed, and arguments. Return "
            '{"done":true} only when the supplied evidence proves the task is complete. '
            "Do not include markdown or prose.\n\nCONTEXT:\n" + context.text
            + "\n\nAUTHORITATIVE CURRENT GOAL:\n" + current_goal
        )
        raw = await self._generate(self._model, prompt)
        try:
            value = self._decode_object(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("planner must return valid capability JSON") from error
        if not isinstance(value, dict):
            raise ValueError("planner must return valid capability JSON")
        expected = {"done", "capability_id", "operation", "target_path", "arguments"}
        if set(value) != expected:
            raise ValueError("planner response must match the exact capability envelope")
        has_completed_action = any(
            source.event_type == "agent.action_completed" for source in context.sources
        )
        if value.get("done") is True:
            if not has_completed_action:
                raise ValueError("planner cannot finish without persisted action evidence")
            return None
        try:
            call_value = {key: item for key, item in value.items() if key != "done"}
            return CapabilityCall.model_validate({**call_value, "project_root": project_root})
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

    @staticmethod
    def _decode_object(raw: str) -> object:
        if len(raw) > 65_536:
            raise ValueError("planner output exceeds the maximum size")
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```" or any(
                line.strip().startswith("```") for line in lines[1:-1]
            ):
                raise ValueError("planner output must contain one JSON object")
            text = "\n".join(lines[1:-1]).strip()
        def no_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result
        return json.loads(text, object_pairs_hook=no_duplicates)


class EventEvidenceVerifier:
    async def verify(
        self, goal: GoalSpec, task: TaskRecord, context: ContextBundle
    ) -> VerificationReport:
        fingerprint = self._project_fingerprint(context)
        completed = [event for event in task.events if event.event_type == "agent.action_completed"]
        accepted = any(event.event_type == "agent.user_accepted" for event in task.events)
        results = {}
        evidence_items = []
        observed_at = datetime.now(UTC)
        for criterion in goal.criteria:
            source = self._criterion_source(criterion.kind.value, criterion.parameters, completed, accepted)
            if criterion.kind.value == "user_acceptance" and source is None:
                results[criterion.criterion_id] = CriterionStatus.pending
                continue
            if source is None:
                results[criterion.criterion_id] = CriterionStatus.failed
                continue
            results[criterion.criterion_id] = CriterionStatus.passed
            child = source.payload.get("child_task_id", "user-acceptance")
            evidence_items.append(
                EvidenceRef(
                    evidence_id=str(uuid7()), task_id=task.task_id, project_id=task.project_id,
                    goal_id=goal.goal_id, goal_revision=goal.revision,
                    criterion_id=criterion.criterion_id,
                    source_ref=f"task:{task.task_id}:child:{child}",
                    project_fingerprint=fingerprint, observed_at=observed_at,
                )
            )
        return VerificationReport(
            report_id=str(uuid7()), task_id=task.task_id, project_id=task.project_id,
            goal_id=goal.goal_id, goal_revision=goal.revision,
            expected_criterion_ids=tuple(item.criterion_id for item in goal.criteria),
            results=results, evidence=tuple(evidence_items), verified_at=datetime.now(UTC),
        )

    @staticmethod
    def _criterion_source(kind: str, parameters, completed, accepted):
        if kind == "user_acceptance":
            return completed[-1] if accepted and completed else None
        if kind == "artifact_exists":
            return next((event for event in reversed(completed) if event.payload.get("artifact_id")), None)
        if kind not in {"project_state", "command_succeeds"}:
            return None
        expected_capability = parameters.get("capability_id")
        expected_operation = parameters.get("operation")
        return next(
            (
                event for event in reversed(completed)
                if (expected_capability is None or event.payload.get("capability_id") == expected_capability)
                and (expected_operation is None or event.payload.get("operation") == expected_operation)
            ),
            None,
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
