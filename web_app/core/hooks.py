from __future__ import annotations

from dataclasses import dataclass

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import TaskCommand, TaskRecord
from web_app.core.service import CoreService


@dataclass(frozen=True)
class _Hook:
    hook_id: str
    call: CapabilityCall


class HookRegistry:
    def __init__(self, core: CoreService, *, project_id: str, principal: str = "user") -> None:
        self._core = core
        self._project_id = project_id
        self._principal = principal
        self._hooks: dict[str, list[_Hook]] = {}
        self._sequence = 0

    def subscribe(self, event_type: str, hook_id: str, capability_call: CapabilityCall) -> None:
        self._hooks.setdefault(event_type, []).append(_Hook(hook_id, capability_call))

    async def publish(self, event_type: str, *, causation: tuple[str, ...]) -> tuple[TaskRecord, ...]:
        records = []
        for hook in self._hooks.get(event_type, ()):
            if hook.hook_id in causation:
                continue
            self._sequence += 1
            task_id = f"hook-{hook.hook_id}-{self._sequence}"
            records.append(await self._core.submit(TaskCommand(
                command_id=f"hook-command-{hook.hook_id}-{self._sequence}",
                task_id=task_id,
                thread_id=f"hook:{hook.hook_id}",
                project_id=self._project_id,
                command_type="hook.trigger",
                payload=hook.call.model_dump(mode="json"),
            ), principal=self._principal))
        return tuple(records)
