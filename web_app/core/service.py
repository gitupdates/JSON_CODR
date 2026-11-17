from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping

from web_app.core.adapters import AdapterEvent, CapabilityAdapter, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.contracts import JsonValue, TaskCommand, TaskEvent, TaskEventDraft, TaskRecord, TaskStatus
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.core.store import TaskStore


logger = logging.getLogger(__name__)


class CoreService:
    def __init__(
        self,
        task_store: TaskStore,
        policy: PolicyService,
        adapters: Mapping[str, CapabilityAdapter],
        *,
        restore_checkpoint: Callable[[str], object] | None = None,
    ) -> None:
        self._tasks = task_store
        self._policy = policy
        self._adapters = dict(adapters)
        self._restore_checkpoint = restore_checkpoint
        self._submission_lock = asyncio.Lock()
        self._runs: dict[str, asyncio.Task[None]] = {}
        self._event_signals: dict[str, asyncio.Event] = {}

    async def submit(self, command: TaskCommand, *, principal: str = "user") -> TaskRecord:
        record = await self.start(command, principal=principal)
        if record.status in {
            TaskStatus.completed,
            TaskStatus.failed,
            TaskStatus.cancelled,
            TaskStatus.interrupted,
        } or record.events[-1].event_type == "task.permission_required":
            return record
        return await self.wait(command.task_id)

    async def start(self, command: TaskCommand, *, principal: str = "user") -> TaskRecord:
        async with self._submission_lock:
            record = self._tasks.create(command)
            if record.status is not TaskStatus.pending or len(record.events) > 1:
                return record
            try:
                call = CapabilityCall.model_validate(command.model_dump(mode="json")["payload"])
                decision = self._policy.evaluate(principal, command.project_id, call)
                if decision.effect is PolicyEffect.deny:
                    self._append(
                        command.task_id,
                        TaskEventDraft(event_type="task.failed", payload={"reason": decision.reason}),
                    )
                    return self._tasks.get(command.task_id)
                if decision.effect is PolicyEffect.require_approval:
                    self._append(
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
                self._append(command.task_id, TaskEventDraft(event_type="task.started"))
                context = ExecutionContext(
                    task_id=command.task_id,
                    project_id=command.project_id,
                    principal=principal,
                    credential_refs=call.credential_refs,
                )
                run = asyncio.create_task(
                    self._execute(command.task_id, adapter, call, context),
                    name=f"json-codr-task-{command.task_id}",
                )
                self._runs[command.task_id] = run
                run.add_done_callback(lambda _task, task_id=command.task_id: self._runs.pop(task_id, None))
            except CapabilityExecutionError as error:
                self._record_execution_error(command.task_id, error)
            except KeyError:
                logger.info("Capability target not found", extra={"task_id": str(command.task_id)})
                self._append(
                    command.task_id,
                    TaskEventDraft(event_type="task.failed", payload={"reason": "capability target not found"}),
                )
            except Exception:
                logger.exception("Capability execution failed", extra={"task_id": str(command.task_id)})
                self._append(
                    command.task_id,
                    TaskEventDraft(event_type="task.failed", payload={"reason": "capability execution failed"}),
                )
            return self._tasks.get(command.task_id)

    async def _execute(self, task_id: str, adapter, call: CapabilityCall, context: ExecutionContext) -> None:
        try:
            async for event in adapter.execute(call, context):
                self._append(task_id, TaskEventDraft(event_type=event.event_type, payload=_redact(event.payload)))
                if self._tasks.get(task_id).status is TaskStatus.cancel_requested:
                    self._append(task_id, TaskEventDraft(event_type="task.cancelled"))
                    return
            self._append(task_id, TaskEventDraft(event_type="task.completed"))
        except CapabilityExecutionError as error:
            self._record_execution_error(task_id, error)
        except KeyError:
            logger.info("Capability target not found", extra={"task_id": task_id})
            self._append(task_id, TaskEventDraft(event_type="task.failed", payload={"reason": "capability target not found"}))
        except Exception:
            logger.exception("Capability execution failed", extra={"task_id": task_id})
            self._append(task_id, TaskEventDraft(event_type="task.failed", payload={"reason": "capability execution failed"}))

    def _record_execution_error(self, task_id: str, error: CapabilityExecutionError) -> None:
        logger.info("Capability execution rejected", extra={"task_id": task_id, "code": error.code})
        self._append(
            task_id,
            TaskEventDraft(event_type="task.failed", payload={"reason": error.safe_message, "code": error.code}),
        )

    def _append(self, task_id: str, event: TaskEventDraft) -> TaskEvent:
        persisted = self._tasks.append(task_id, event)
        self._event_signals.setdefault(task_id, asyncio.Event()).set()
        return persisted

    async def wait(self, task_id: str) -> TaskRecord:
        run = self._runs.get(task_id)
        if run is not None:
            await asyncio.shield(run)
        return self._tasks.get(task_id)

    async def wait_for_events(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        while True:
            events = self.subscribe(task_id, after_sequence)
            if events:
                return events
            record = self._tasks.get(task_id)
            if record.status in {
                TaskStatus.completed,
                TaskStatus.failed,
                TaskStatus.cancelled,
                TaskStatus.interrupted,
            }:
                return ()
            signal = self._event_signals.setdefault(task_id, asyncio.Event())
            signal.clear()
            events = self.subscribe(task_id, after_sequence)
            if events:
                return events
            await signal.wait()

    def steer(self, task_id: str, user_input: str) -> TaskEvent:
        return self._append(task_id, TaskEventDraft(event_type="task.steered", payload={"input": user_input}))

    def cancel(self, task_id: str) -> TaskRecord:
        record = self._tasks.request_cancel(task_id)
        self._event_signals.setdefault(task_id, asyncio.Event()).set()
        return record

    def subscribe(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        return self._tasks.events(task_id, after_sequence)

    async def retry(self, command: TaskCommand, *, principal: str = "user") -> TaskRecord:
        return await self.submit(command, principal=principal)

    def restore(self, checkpoint_id: str) -> None:
        if self._restore_checkpoint is None:
            raise LookupError("checkpoint restore is unavailable")
        self._restore_checkpoint(checkpoint_id)


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
