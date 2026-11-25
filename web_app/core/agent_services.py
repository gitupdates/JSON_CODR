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
        "additionalProperties": False,
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
    installed = config.get("installed_models")
    if (
        fallback and isinstance(verified, (list, tuple)) and fallback in verified
        and isinstance(installed, (list, tuple)) and fallback in installed
    ):
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
    def __init__(
        self,
        generate: Callable[[str, str], Awaitable[str]],
        *,
        model: str,
        generate_batch: Callable[[str, str], Awaitable[str]] | None = None,
    ) -> None:
        self._generate = generate
        self._model = model
        self._generate_batch = generate_batch

    async def plan_batch(self, context: ContextBundle) -> tuple[CapabilityCall, ...]:
        if self._generate_batch is None:
            call = await self.plan(context)
            return () if call is None else (call,)
        project_root = self._project_root(context)
        current_goal = next(
            (
                source.content for source in reversed(context.sources)
                if source.event_type == "agent.goal_registered"
            ),
            "",
        )
        prompt = (
            "Act as a local coding planner. Return one finite ordered call set as a JSON object "
            "with exactly one calls array containing 1 to 8 exact capability calls. Each call "
            "must contain exactly capability_id, operation, target_path, and arguments. Include "
            "every action needed for this bounded attempt in execution order. Never include a "
            "project_root, credential, wildcard, markdown, or prose. Use these exact core "
            "contracts: project.read uses operation read and arguments {}; project.search uses "
            "operation search, target_path '.', and arguments {\"query\":\"text\"}; project.patch "
            "uses operation replace and arguments {\"content\":\"the complete UTF-8 replacement "
            "file content\"}.\n\nCONTEXT:\n" + context.text
            + "\n\nAUTHORITATIVE CURRENT GOAL:\n" + current_goal
        )
        raw = await self._generate_batch(self._effective_model(context), prompt)
        value = self._decode_object(raw)
        if not isinstance(value, dict) or set(value) != {"calls"}:
            raise ValueError("batch planner must return exactly one calls array")
        raw_calls = value.get("calls")
        if not isinstance(raw_calls, list) or not 1 <= len(raw_calls) <= 8:
            raise ValueError("batch planner calls must contain 1 to 8 items")
        expected = {"capability_id", "operation", "target_path", "arguments"}
        calls = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict) or set(raw_call) != expected:
                raise ValueError("batch planner call must match the exact capability envelope")
            contract_error = self._core_contract_error(raw_call)
            if contract_error is not None:
                raise ValueError(f"batch planner call is invalid: {contract_error}")
            try:
                calls.append(CapabilityCall.model_validate({**raw_call, "project_root": project_root}))
            except ValidationError as error:
                raise ValueError("batch planner call must be valid capability JSON") from error
        return tuple(calls)

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
            "Do not include markdown or prose. Use these exact core capability contracts: "
            'project.read uses operation "read", target_path, and arguments {}; '
            'project.search uses operation "search", target_path ".", and arguments {"query":"text"}; '
            'project.patch uses operation "replace", target_path, and arguments '
            '{"content":"the complete UTF-8 replacement file content"}. '
            "Never invent argument names.\n\nCONTEXT:\n" + context.text
            + "\n\nAUTHORITATIVE CURRENT GOAL:\n" + current_goal
        )
        expected = {"done", "capability_id", "operation", "target_path", "arguments"}
        has_completed_action = any(
            source.event_type == "agent.action_completed" for source in context.sources
        )
        model = self._effective_model(context)
        for attempt in range(3):
            raw = await self._generate(model, prompt)
            try:
                value = self._decode_object(raw)
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError("planner must return valid capability JSON") from error
            if not isinstance(value, dict):
                raise ValueError("planner must return valid capability JSON")
            if set(value) == expected - {"done"}:
                value = {"done": False, **value}
            if set(value) != expected:
                contract_error = (
                    "The planner envelope must contain exactly these keys: done, capability_id, "
                    "operation, target_path, arguments; received keys: "
                    f"{sorted(str(key) for key in value)}."
                )
                if attempt == 2:
                    raise ValueError(
                        "planner response must match the exact capability envelope; "
                        f"received keys: {sorted(str(key) for key in value)}"
                    )
                prompt += (
                    f"\n\nCORRECTION: {contract_error} "
                    "Return the single corrected capability call needed to begin the task."
                )
                continue
            if value.get("done") is True:
                if has_completed_action:
                    return None
                contract_error = "No completed action evidence exists. done must be false."
            else:
                contract_error = self._core_contract_error(value)
                if contract_error is None:
                    break
            if attempt == 2:
                if value.get("done") is True:
                    raise ValueError("planner cannot finish without persisted action evidence")
                raise ValueError(f"planner correction failed: {contract_error}")
            prompt += (
                f"\n\nCORRECTION: {contract_error} "
                "Return the single corrected capability call needed to begin the task."
            )
        try:
            call_value = {key: item for key, item in value.items() if key != "done"}
            return CapabilityCall.model_validate({**call_value, "project_root": project_root})
        except ValidationError as error:
            raise ValueError("planner must return valid capability JSON") from error

    def _effective_model(self, context: ContextBundle) -> str:
        model = self._model
        for source in reversed(context.sources):
            if source.event_type != "agent.model_route":
                continue
            try:
                route = json.loads(source.content)
                candidate = route.get("payload", {}).get("effective_model")
            except (json.JSONDecodeError, AttributeError):
                candidate = None
            if isinstance(candidate, str) and candidate:
                model = candidate
                break
        return model

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
        decoder = json.JSONDecoder(object_pairs_hook=no_duplicates)
        values = []
        offset = 0
        while offset < len(text):
            value, offset = decoder.raw_decode(text, offset)
            values.append(value)
            while offset < len(text) and text[offset].isspace():
                offset += 1
        if len(values) == 1:
            return values[0]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError("planner output must contain one JSON object")
        merged = {}
        for value in values:
            if set(merged).intersection(value):
                raise ValueError("planner output contains conflicting JSON objects")
            merged.update(value)
        expected = {"done", "capability_id", "operation", "target_path", "arguments"}
        if set(merged) != expected:
            raise ValueError("planner output must contain one complete capability envelope")
        return merged

    @staticmethod
    def _core_contract_error(value: dict) -> str | None:
        capability_id = value.get("capability_id")
        operation = value.get("operation")
        target_path = value.get("target_path")
        arguments = value.get("arguments")
        if capability_id not in {"project.read", "project.search", "project.patch"}:
            return None
        if not isinstance(target_path, str) or not target_path:
            return f"{capability_id} requires a non-empty target_path."
        if not isinstance(arguments, dict):
            return f"{capability_id} requires an arguments object."
        if capability_id == "project.read":
            if operation != "read" or arguments:
                return 'project.read requires operation "read" and arguments {}.'
            return None
        if capability_id == "project.search":
            if (
                operation != "search" or target_path != "."
                or set(arguments) != {"query"}
                or not isinstance(arguments.get("query"), str)
            ):
                return (
                    'project.search requires operation "search", target_path ".", '
                    'and arguments {"query":"text"}.'
                )
            return None
        if (
            operation != "replace"
            or set(arguments) != {"content"}
            or not isinstance(arguments.get("content"), str)
        ):
            return (
                'project.patch requires operation "replace" and exactly '
                'arguments {"content":"the complete UTF-8 replacement file content"}.'
            )
        return None


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
