from __future__ import annotations

import asyncio
from collections.abc import Mapping

from web_app.core.adapters import AdapterEvent, CapabilityAdapter, CapabilityCall, ExecutionContext
from web_app.core.contracts import JsonValue, TaskCommand, TaskEvent, TaskEventDraft, TaskRecord, TaskStatus
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.core.store import TaskStore


class CoreService:
    def __init__(
        self,
        task_store: TaskStore,
        policy: PolicyService,
        adapters: Mapping[str, CapabilityAdapter],
    ) -> None:
        self._tasks = task_store
        self._policy = policy
        self._adapters = dict(adapters)
        self._submission_lock = asyncio.Lock()

    async def submit(self, command: TaskCommand, *, principal: str = "user") -> TaskRecord:
        async with self._submission_lock:
            record = self._tasks.create(command)
            if record.status is not TaskStatus.pending or len(record.events) > 1:
                return record
            try:
                call = CapabilityCall.model_validate(dict(command.payload))
                decision = self._policy.evaluate(principal, command.project_id, call)
                if decision.effect is PolicyEffect.deny:
                    self._tasks.append(
                        command.task_id,
                        TaskEventDraft(event_type="task.failed", payload={"reason": decision.reason}),
                    )
                    return self._tasks.get(command.task_id)
                if decision.effect is PolicyEffect.require_approval:
                    self._tasks.append(
                        command.task_id,
                        TaskEventDraft(
                            event_type="task.permission_required",
                            payload={"capability_id": call.capability_id, "operation": call.operation},
                        ),
                    )
                    return self._tasks.get(command.task_id)
                adapter = self._adapters.get(call.capability_id)
                if adapter is None:
                    raise LookupError("capability adapter unavailable")
                self._tasks.append(command.task_id, TaskEventDraft(event_type="task.started"))
                context = ExecutionContext(
                    task_id=command.task_id,
                    project_id=command.project_id,
                    principal=principal,
                    credential_refs=call.credential_refs,
                )
                async for event in adapter.execute(call, context):
                    self._tasks.append(
                        command.task_id,
                        TaskEventDraft(event_type=event.event_type, payload=_redact(event.payload)),
                    )
                self._tasks.append(command.task_id, TaskEventDraft(event_type="task.completed"))
            except Exception:
                self._tasks.append(
                    command.task_id,
                    TaskEventDraft(event_type="task.failed", payload={"reason": "capability execution failed"}),
                )
            return self._tasks.get(command.task_id)

    def steer(self, task_id: str, user_input: str) -> TaskEvent:
        return self._tasks.append(task_id, TaskEventDraft(event_type="task.steered", payload={"input": user_input}))

    def cancel(self, task_id: str) -> TaskRecord:
        return self._tasks.request_cancel(task_id)

    def subscribe(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        return self._tasks.events(task_id, after_sequence)

    async def retry(self, command: TaskCommand, *, principal: str = "user") -> TaskRecord:
        return await self.submit(command, principal=principal)

    def restore(self, checkpoint_id: str) -> None:
        raise NotImplementedError("checkpoint restore is provided by the project adapter")


def _redact(value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    sensitive = {"api_key", "authorization", "cookie", "credential", "credential_refs", "password", "secret", "token"}
    result: dict[str, JsonValue] = {}
    for key, item in value.items():
        if key.casefold() in sensitive:
            continue
        if isinstance(item, Mapping):
            result[key] = _redact(item)
        elif isinstance(item, list | tuple):
            result[key] = [_redact(entry) if isinstance(entry, Mapping) else entry for entry in item]
        else:
            result[key] = item
    return result
