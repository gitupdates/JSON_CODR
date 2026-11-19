from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from pydantic import ValidationError

from web_app.core.adapters import CapabilityCall
from web_app.core.context_service import ContextBundle
from web_app.core.contracts import TaskCommand
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
