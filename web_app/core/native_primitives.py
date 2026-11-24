from __future__ import annotations

import sys
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
from web_app.core.command_runtime import CommandRuntime
from web_app.core.verification_profiles import VerificationProfileStore


class NativePrimitiveAdapter:
    capability_ids = frozenset({"native.read", "native.write", "native.edit", "native.shell"})

    def __init__(self, project, terminal, command_runtime: CommandRuntime | None = None) -> None:
        self._project = project
        self._terminal = terminal
        self._commands = command_runtime or CommandRuntime(
            VerificationProfileStore(self._project._root.parent)
        )

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        if call.capability_id not in self.capability_ids:
            raise ValueError(f"unsupported native capability: {call.capability_id}")
        if call.capability_id == "native.read":
            line_range = call.arguments.get("line_range")
            parsed_range = None
            if line_range is not None:
                if not isinstance(line_range, (list, tuple)) or len(line_range) != 2:
                    raise ValueError("native read line_range requires start and end")
                parsed_range = (int(line_range[0]), int(line_range[1]))
            content = self._project.read_lines(call.project_root, call.target_path, parsed_range)
            yield AdapterEvent(
                event_type="native.read.completed",
                payload={"route": "native", "path": str(call.target_path), "content": content},
            )
            return
        if call.capability_id == "native.write":
            content = call.arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("native write requires string content")
            checkpoint = self._project.atomic_write(call.project_root, call.target_path, content)
            yield AdapterEvent(event_type="checkpoint.created", payload=checkpoint.model_dump(mode="json"))
            yield AdapterEvent(
                event_type="native.write.completed",
                payload={"route": "native", "path": str(call.target_path), "checkpoint_id": checkpoint.checkpoint_id},
            )
            return
        if call.capability_id == "native.edit":
            diff_hunk = call.arguments.get("diff_hunk")
            if not isinstance(diff_hunk, str):
                raise ValueError("native edit requires a unified diff hunk")
            checkpoint = self._project.apply_edit(call.project_root, call.target_path, diff_hunk)
            yield AdapterEvent(event_type="checkpoint.created", payload=checkpoint.model_dump(mode="json"))
            yield AdapterEvent(
                event_type="native.edit.completed",
                payload={"route": "native", "path": str(call.target_path), "checkpoint_id": checkpoint.checkpoint_id},
            )
            return
        if "argv" in call.arguments:
            raise ValueError("autonomous native shell requires a profile_id; raw argv is interactive-Administrator only")
        profile_id = call.arguments.get("profile_id")
        values = call.arguments.get("values", {})
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("autonomous native shell requires a profile_id")
        if not isinstance(values, dict):
            raise ValueError("native shell profile values must be an object")
        yield AdapterEvent(
            event_type="native.shell.started",
            payload={"route": "native", "profile_id": profile_id},
        )
        result = await self._commands.run_profile(
            profile_id=profile_id, values=values, project_root=call.project_root,
        )
        yield AdapterEvent(
            event_type="native.shell.completed",
            payload={"route": "native", "profile_id": profile_id, **result.model_dump(mode="json")},
        )
