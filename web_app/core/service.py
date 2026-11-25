from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityAdapter, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.approval import ApprovalEnvelopeLease, ApprovalLease, ApprovalStore
from web_app.core.canonical import canonical_digest
from web_app.core.capability_registry import CapabilityRegistry
from web_app.core.contracts import JsonValue, TaskCommand, TaskEvent, TaskEventDraft, TaskRecord, TaskStatus
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.core.project_registry import ProjectRegistry
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
        agent_runner: Callable[[str], Awaitable[TaskRecord]] | None = None,
        approval_store: ApprovalStore | None = None,
        project_fingerprint: Callable[[str], str] | None = None,
        registry: CapabilityRegistry | None = None,
        project_roots: Mapping[str, str | Path] | ProjectRegistry | None = None,
    ) -> None:
        self._tasks = task_store
        self._policy = policy
        self._adapters = dict(adapters)
        self._registry = registry or CapabilityRegistry.default()
        self._registry.require_registered(self._adapters)
        self._project_roots = project_roots
        self._restore_checkpoint = restore_checkpoint
        self._agent_runner = agent_runner
        self._approval_store = approval_store
        self._project_fingerprint = project_fingerprint
        self._submission_lock = asyncio.Lock()
        self._runs: dict[str, asyncio.Task[None]] = {}
        self._event_signals: dict[str, asyncio.Event] = {}

    async def submit(
        self,
        command: TaskCommand,
        *,
        principal: str = "user",
        principal_scopes: tuple[str, ...] = (),
        approval_lease: ApprovalLease | ApprovalEnvelopeLease | None = None,
        trusted_schedule_id: str | None = None,
    ) -> TaskRecord:
        record = await self.start(
            command,
            principal=principal,
            principal_scopes=principal_scopes,
            approval_lease=approval_lease,
            trusted_schedule_id=trusted_schedule_id,
        )
        if record.status in {
            TaskStatus.completed,
            TaskStatus.failed,
            TaskStatus.cancelled,
            TaskStatus.interrupted,
        } or record.events[-1].event_type == "task.permission_required":
            return record
        return await self.wait(command.task_id)

    async def start(
        self,
        command: TaskCommand,
        *,
        principal: str = "user",
        principal_scopes: tuple[str, ...] = (),
        approval_lease: ApprovalLease | ApprovalEnvelopeLease | None = None,
        trusted_schedule_id: str | None = None,
    ) -> TaskRecord:
        async with self._submission_lock:
            if command.command_type != "agent.run":
                call = self._prepare_call(
                    command.project_id,
                    CapabilityCall.model_validate(command.model_dump(mode="json")["payload"]),
                    trusted_schedule_id=trusted_schedule_id,
                )
                command = command.model_copy(update={"payload": call.model_dump(mode="json")})
            record = self._tasks.create(command)
            if command.command_type == "agent.run":
                bound = next(
                    (event for event in record.events if event.event_type == "task.principal_bound"),
                    None,
                )
                if bound is None:
                    self._append(command.task_id, TaskEventDraft(
                        event_type="task.principal_bound",
                        payload={"principal": principal, "principal_scopes": list(principal_scopes)},
                    ))
                    record = self._tasks.get(command.task_id)
                elif bound.payload.get("principal") != principal:
                    raise PermissionError("agent task principal does not match")
                if record.status in {
                    TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.interrupted,
                } or command.task_id in self._runs:
                    return record
                if self._agent_runner is None:
                    self._append(
                        command.task_id,
                        TaskEventDraft(event_type="task.failed", payload={"reason": "agent runtime unavailable"}),
                    )
                    return self._tasks.get(command.task_id)
                if record.status is TaskStatus.pending:
                    self._append(command.task_id, TaskEventDraft(event_type="task.started"))
                run = asyncio.create_task(
                    self._execute_agent(command.task_id), name=f"json-codr-agent-{command.task_id}"
                )
                self._runs[command.task_id] = run
                run.add_done_callback(lambda _task, task_id=command.task_id: self._runs.pop(task_id, None))
                return self._tasks.get(command.task_id)
            permission_wait = record.events[-1].event_type == "task.permission_required"
            if record.status is not TaskStatus.pending or (len(record.events) > 1 and not permission_wait):
                return record
            try:
                call = self._registry.normalize(CapabilityCall.model_validate(command.model_dump(mode="json")["payload"]))
                decision = self._policy.evaluate(
                    principal,
                    command.project_id,
                    call,
                    trusted_schedule_id=trusted_schedule_id,
                )
                if decision.effect is PolicyEffect.deny:
                    self._append(
                        command.task_id,
                        TaskEventDraft(event_type="task.failed", payload={"reason": decision.reason}),
                    )
                    return self._tasks.get(command.task_id)
                if decision.effect is PolicyEffect.require_approval:
                    if approval_lease is not None:
                        if approval_lease.call_digest != canonical_digest(call.model_dump(mode="json")):
                            raise PermissionError("approval lease does not match capability call")
                    elif self._approval_store is not None:
                        if self._project_fingerprint is None:
                            raise RuntimeError("exact approval requires project fingerprinting")
                        proposal = self._approval_store.propose(
                            principal=principal,
                            project_id=command.project_id,
                            task_id=command.task_id,
                            step_id=command.task_id,
                            step_revision=1,
                            call=call,
                            project_fingerprint=self._project_fingerprint(call.project_root),
                        )
                        self._append(
                            command.task_id,
                            TaskEventDraft(
                                event_type="task.permission_required",
                                payload={
                                    "capability_id": call.capability_id,
                                    "operation": call.operation,
                                    "proposal_id": proposal.proposal_id,
                                    "call_digest": proposal.call_digest,
                                    "project_fingerprint": proposal.project_fingerprint,
                                    "expires_at": proposal.expires_at.isoformat(),
                                },
                            ),
                        )
                        return self._tasks.get(command.task_id)
                    else:
                        self._append(
                            command.task_id,
                            TaskEventDraft(
                                event_type="task.permission_required",
                                payload={"capability_id": call.capability_id, "operation": call.operation},
                            ),
                        )
                        return self._tasks.get(command.task_id)
                if decision.effect is PolicyEffect.require_approval and approval_lease is None:
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
                    principal_scopes=principal_scopes,
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

    async def _execute_agent(self, task_id: str) -> None:
        try:
            await self._agent_runner(task_id)
        except Exception:
            logger.exception("Agent execution failed", extra={"task_id": task_id})
            if self._tasks.get(task_id).status not in {
                TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.interrupted,
            }:
                self._append(
                    task_id,
                    TaskEventDraft(event_type="task.failed", payload={"reason": "agent execution failed"}),
                )

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

    async def shutdown(self) -> None:
        runs = tuple(self._runs.values())
        for run in runs:
            run.cancel()
        if runs:
            await asyncio.gather(*runs, return_exceptions=True)
        self._runs.clear()

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
        if self._approval_store is not None:
            self._approval_store.revoke_task(task_id)
        self._event_signals.setdefault(task_id, asyncio.Event()).set()
        return record

    async def approve(
        self,
        task_id: str,
        *,
        principal: str = "user",
        principal_scopes: tuple[str, ...] = (),
        scope: str = "project",
        proposal_id: str | None = None,
        envelope_id: str | None = None,
    ) -> TaskRecord:
        command = self._tasks.command(task_id)
        record = self._tasks.get(task_id)
        if command.command_type == "agent.run":
            approval = next(
                (event for event in reversed(record.events) if event.event_type == "agent.approval_required"),
                None,
            )
            if approval is None:
                raise ValueError("task is not awaiting approval")
            requested_envelope = approval.payload.get("envelope_id")
            if isinstance(requested_envelope, str):
                if envelope_id != requested_envelope:
                    raise ValueError("exact approval envelope id is required")
                if self._approval_store is None or self._project_fingerprint is None:
                    raise RuntimeError("approval envelopes require an approval store and project fingerprinting")
                project_root = approval.payload.get("project_root")
                task_revision = approval.payload.get("task_revision")
                if not isinstance(project_root, str) or not isinstance(task_revision, int):
                    raise ValueError("approval envelope request is invalid")
                envelope = self._approval_store.approve_envelope(
                    envelope_id,
                    principal=principal,
                    project_id=command.project_id,
                    project_fingerprint=self._project_fingerprint(project_root),
                    task_revision=task_revision,
                )
                self._append(task_id, TaskEventDraft(
                    event_type="agent.approval_granted",
                    payload={
                        "envelope_id": envelope.envelope_id,
                        "task_revision": envelope.task_revision,
                        "approved_at": envelope.approved_at.isoformat() if envelope.approved_at else None,
                    },
                ))
                return await self.submit(
                    command, principal=principal, principal_scopes=principal_scopes,
                )
            child_task_id = approval.payload.get("child_task_id")
            if not isinstance(child_task_id, str):
                raise ValueError("approval request is invalid")
            await self.approve(
                child_task_id, principal=principal, principal_scopes=principal_scopes,
                scope=scope, proposal_id=proposal_id,
            )
            return await self.submit(
                command, principal=principal, principal_scopes=principal_scopes,
            )
        call = self._registry.normalize(CapabilityCall.model_validate(command.payload))
        if self._approval_store is not None:
            if proposal_id is None:
                raise ValueError("exact approval proposal id is required")
            if self._project_fingerprint is None:
                raise RuntimeError("exact approval requires project fingerprinting")
            lease = self._approval_store.consume(
                proposal_id,
                principal=principal,
                call=call,
                project_fingerprint=self._project_fingerprint(call.project_root),
                step_revision=1,
            )
            if not record.events or record.events[-1].event_type != "task.permission_required":
                raise ValueError("task is not awaiting approval")
            return await self.submit(
                command,
                principal=principal,
                principal_scopes=principal_scopes,
                approval_lease=lease,
                trusted_schedule_id=call.schedule_id,
            )
        if not record.events or record.events[-1].event_type != "task.permission_required":
            raise ValueError("task is not awaiting approval")
        self._policy.grant(
            principal,
            command.project_id,
            call,
            scope=scope,
            schedule_id=call.schedule_id if scope == "schedule" else None,
        )
        return await self.submit(
            command,
            principal=principal,
            principal_scopes=principal_scopes,
            trusted_schedule_id=call.schedule_id,
        )

    def approval_required(
        self, project_id: str, call: CapabilityCall, *, principal: str = "user"
    ) -> bool:
        normalized = self._prepare_call(project_id, call, trusted_schedule_id=None)
        return self._policy.evaluate(principal, project_id, normalized).effect is PolicyEffect.require_approval

    def subscribe(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        return self._tasks.events(task_id, after_sequence)

    async def retry(self, command: TaskCommand, *, principal: str = "user") -> TaskRecord:
        return await self.submit(command, principal=principal)

    def restore(self, checkpoint_id: str) -> None:
        if self._restore_checkpoint is None:
            raise LookupError("checkpoint restore is unavailable")
        self._restore_checkpoint(checkpoint_id)

    def _prepare_call(
        self,
        project_id: str,
        call: CapabilityCall,
        *,
        trusted_schedule_id: str | None,
    ) -> CapabilityCall:
        if call.schedule_id != trusted_schedule_id:
            raise ValueError("schedule authority must come from trusted scheduler context")
        call = self._registry.normalize(call)
        root = self._resolve_project_root(project_id)
        if root is None:
            return call
        supplied = Path(call.project_root).resolve()
        if supplied != root:
            raise ValueError("capability project root does not match the registered project root")
        return call.model_copy(update={"project_root": str(root)})

    def prepare_capability_call(
        self,
        project_id: str,
        call: CapabilityCall,
        *,
        trusted_schedule_id: str | None = None,
    ) -> CapabilityCall:
        """Return the server-bound form safe to persist or execute."""
        return self._prepare_call(project_id, call, trusted_schedule_id=trusted_schedule_id)

    def register_delegated_worktree(self, parent_project_id: str, root: str | Path) -> str:
        if not isinstance(self._project_roots, ProjectRegistry):
            raise RuntimeError("delegated worktrees require a project registry")
        return self._project_roots.register_child(parent_project_id, root).project_id

    def register_project_root(self, project_id: str, root: str | Path) -> str:
        if not isinstance(self._project_roots, ProjectRegistry):
            raise RuntimeError("capability execution requires a project registry")
        return self._project_roots.register(root, project_id=project_id).project_id

    def _resolve_project_root(self, project_id: str) -> Path | None:
        if self._project_roots is None:
            raise RuntimeError("capability execution requires a project registry")
        if isinstance(self._project_roots, ProjectRegistry):
            return self._project_roots.resolve(project_id)
        raise RuntimeError("capability execution requires a project registry")


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
