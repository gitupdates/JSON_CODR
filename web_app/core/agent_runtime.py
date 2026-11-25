from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from web_app.core.adapters import CapabilityCall
from web_app.core.approval import ApprovalEnvelopeLease, ApprovalStore, requires_separate_approval
from web_app.core.agent_verification import EvidenceResolver, FailureNormalizer, StaleEvidence
from web_app.core.canonical import canonical_digest
from web_app.core.contracts import GoalSpec, TaskCommand, TaskEventDraft, TaskStatus
from web_app.core.project_intelligence import ProjectReader


PLANNER_CONTEXT_BUDGET = 3_000
_WAITING_FOR_APPROVAL = object()


class AgentRuntime:
    def __init__(
        self, task_store, core_service, context, planner, verifier, project_fingerprint,
        project_reader_resolver=None, verifier_identity=None, approval_store: ApprovalStore | None = None,
    ) -> None:
        self._tasks = task_store
        self._core = core_service
        self.context = context
        self._planner = planner
        self._verifier = verifier
        self._project_fingerprint = project_fingerprint
        self._evidence = EvidenceResolver()
        self._project_reader_resolver = project_reader_resolver
        self._verifier_identity = verifier_identity
        self._approval_store = approval_store

    def automatic_lesson_activation_ready(self) -> bool:
        return bool(
            self._verifier_identity is not None
            and self._verifier_identity.automatic_lesson_activation_ready()
        )

    async def run(self, task_id: str):
        root = self._tasks.get(task_id)
        if root.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}:
            return root
        root_command = self._tasks.command(task_id)
        goal = GoalSpec.model_validate(root_command.payload.get("goal_spec"))
        if not any(event.event_type == "agent.goal_registered" for event in root.events):
            self._tasks.append(
                task_id,
                TaskEventDraft(event_type="agent.goal_registered", payload=goal.model_dump(mode="json")),
            )
        if not any(event.event_type == "agent.model_route" for event in root.events):
            requested_model = root_command.payload.get("requested_model")
            effective_model = root_command.payload.get("effective_model")
            if isinstance(effective_model, str) and effective_model:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(event_type="agent.model_route", payload={
                        "requested_model": requested_model,
                        "effective_model": effective_model,
                        "route": root_command.payload.get("route", "broker_verified"),
                    }),
                )
        if not goal.accepted:
            if not any(event.event_type == "agent.goal_acceptance_required" for event in root.events):
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.goal_acceptance_required",
                        payload={"goal_id": goal.goal_id, "goal_revision": goal.revision},
                    ),
                )
            return self._tasks.get(task_id)
        if not any(event.event_type == "agent.started" for event in root.events):
            self._tasks.append(task_id, TaskEventDraft(event_type="agent.started"))
            self._tasks.append(
                task_id,
                TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "planning"}),
            )
        resolved = None if self._project_reader_resolver is None else self._project_reader_resolver(root_command)
        if resolved is not None:
            reader, target_path = resolved
            self.context.capture_project(
                root.thread_id,
                task_id,
                reader,
                target_path=target_path if isinstance(target_path, str) else ".",
                prioritize_references_in=goal.objective,
            )
        root = self._tasks.get(task_id)
        reconciled_action = False
        for approval in (
            event for event in root.events if event.event_type == "agent.approval_required"
        ):
            child_task_id = approval.payload.get("child_task_id")
            step_id = approval.payload.get("step_id")
            if not isinstance(child_task_id, str) or not isinstance(step_id, str):
                continue
            if any(
                event.event_type == "agent.action_completed" and event.payload.get("step_id") == step_id
                for event in root.events
            ):
                continue
            child = self._tasks.get(child_task_id)
            if child.status is not TaskStatus.completed:
                continue
            child_call = CapabilityCall.model_validate(self._tasks.command(child_task_id).payload)
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.action_completed",
                payload={
                    "capability_id": child_call.capability_id,
                    "operation": child_call.operation,
                    "call_digest": canonical_digest(child_call.model_dump(mode="json")),
                    "child_task_id": child_task_id,
                    "step_id": step_id,
                    "project_fingerprint": self._project_fingerprint(child_call.project_root),
                    "batch_id": approval.payload.get("batch_id"),
                    "batch_ordinal": approval.payload.get("batch_ordinal"),
                },
            ))
            batch_id = approval.payload.get("batch_id")
            batch_ordinal = approval.payload.get("batch_ordinal")
            if isinstance(batch_id, str) and isinstance(batch_ordinal, int):
                self._tasks.append(task_id, TaskEventDraft(
                    event_type="agent.preflight_call_finished",
                    payload={
                        "batch_id": batch_id, "ordinal": batch_ordinal,
                        "outcome": "completed", "child_task_id": child_task_id,
                    },
                ))
            if resolved is not None:
                reader, target_path = resolved
                self.context.capture_project(
                    root.thread_id, task_id, reader,
                    target_path=target_path if isinstance(target_path, str) else ".",
                    prioritize_references_in=goal.objective,
                )
            reconciled_action = True
        if reconciled_action and not self._has_pending_preflight(self._tasks.get(task_id)):
            context = self.context.assemble(root.thread_id, task_id, PLANNER_CONTEXT_BUDGET)
            completed = await self._complete_if_verified(
                task_id, goal, root_command, context, record_failure=True
            )
            if completed is not None:
                return completed
        while True:
            root = self._tasks.get(task_id)
            if root.status is TaskStatus.cancel_requested:
                self._tasks.append(task_id, TaskEventDraft(event_type="task.cancelled"))
                return self._tasks.get(task_id)
            context = self.context.assemble(root.thread_id, task_id, PLANNER_CONTEXT_BUDGET)
            planned = await self._next_planned_call(task_id, goal, root, context)
            root = self._tasks.get(task_id)
            if root.status is TaskStatus.cancel_requested:
                self._tasks.append(task_id, TaskEventDraft(event_type="task.cancelled"))
                return self._tasks.get(task_id)
            if planned is _WAITING_FOR_APPROVAL:
                return root
            if planned is None:
                call = None
                batch_id = None
                batch_ordinal = None
                batch_size = None
                envelope_id = None
            else:
                call, batch_id, batch_ordinal, batch_size, envelope_id = planned
            if call is None:
                completed = await self._complete_if_verified(
                    task_id, goal, root_command, context, record_failure=True
                )
                if completed is not None:
                    return completed
                root = self._tasks.get(task_id)
                verification_failures = sum(
                    event.event_type == "agent.verification_failed" for event in root.events
                )
                if verification_failures >= 3:
                    self._tasks.append(
                        task_id,
                        TaskEventDraft(
                            event_type="agent.blocked",
                            payload={"reason": "verification repair budget exhausted"},
                        ),
                    )
                    return self._tasks.get(task_id)
                continue
            call = self._core.prepare_capability_call(root.project_id, call)
            call_digest = canonical_digest(call.model_dump(mode="json"))
            project_fingerprint = self._project_fingerprint(call.project_root)
            repeated_success = next(
                (
                    event for event in root.events
                    if event.event_type == "agent.action_completed"
                    and event.payload.get("call_digest") == call_digest
                    and event.payload.get("project_fingerprint") == project_fingerprint
                ),
                None,
            )
            if repeated_success is not None and batch_id is None:
                completed = await self._complete_if_verified(
                    task_id, goal, root_command, context, record_failure=True
                )
                if completed is not None:
                    return completed
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.blocked",
                        payload={
                            "reason": "unchanged successful action loop",
                            "call_digest": call_digest,
                            "project_fingerprint": project_fingerprint,
                        },
                    ),
                )
                return self._tasks.get(task_id)
            prior_failures = [
                event for event in root.events
                if event.event_type == "agent.action_failed"
            ]
            repeated = next(
                (
                    event for event in prior_failures
                    if event.payload.get("call_digest") == call_digest
                    and event.payload.get("project_fingerprint") == project_fingerprint
                ),
                None,
            )
            if repeated is not None:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.blocked",
                        payload={
                            "reason": "unchanged repair loop",
                            "failure_signature": repeated.payload.get("failure_signature"),
                            "project_fingerprint": project_fingerprint,
                        },
                    ),
                )
                return self._tasks.get(task_id)
            criterion_id = goal.criteria[0].criterion_id
            criterion_attempts = sum(
                event.payload.get("criterion_id") == criterion_id for event in prior_failures
            )
            if criterion_attempts >= 3:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.blocked",
                        payload={"reason": "repair budget exhausted", "criterion_id": criterion_id},
                    ),
                )
                return self._tasks.get(task_id)
            planned_steps = [event for event in root.events if event.event_type == "agent.step_planned"]
            last_step_id = None if not planned_steps else planned_steps[-1].payload.get("step_id")
            last_step_resolved = last_step_id is not None and any(
                event.event_type in {"agent.action_completed", "agent.action_failed"}
                and event.payload.get("step_id") == last_step_id
                for event in root.events
            )
            step_number = len(planned_steps) + 1 if last_step_resolved or not planned_steps else len(planned_steps)
            plan_id = f"plan-{task_id}"
            step_id = f"step-{step_number}"
            child_id = str(uuid5(NAMESPACE_URL, f"json-codr:{task_id}:{step_id}:task"))
            command_id = str(uuid5(NAMESPACE_URL, f"json-codr:{task_id}:{step_id}:command"))
            child_command = TaskCommand(
                command_id=command_id,
                task_id=child_id,
                thread_id=root.thread_id,
                project_id=root.project_id,
                parent_task_id=task_id,
                command_type=call.capability_id,
                payload=call.model_dump(mode="json"),
            )
            self._tasks.plan_step_and_create_child(
                task_id,
                plan_id,
                1,
                step_id,
                child_command,
            )
            envelope_lease: ApprovalEnvelopeLease | None = None
            principal, principal_scopes = self._principal_context(root)
            if (
                isinstance(envelope_id, str)
                and self._approval_store is not None
                and self._core.approval_required(root.project_id, call, principal=principal)
                and not requires_separate_approval(call)
            ):
                envelope_lease = self._approval_store.reserve_envelope_call(
                    envelope_id,
                    principal=principal,
                    project_id=root.project_id,
                    call=call,
                    project_fingerprint=self._project_fingerprint(call.project_root),
                    task_revision=goal.revision,
                )
            child = await self._core.submit(
                child_command,
                principal=principal,
                principal_scopes=principal_scopes,
                approval_lease=envelope_lease,
            )
            if envelope_lease is not None:
                resulting_fingerprint = self._project_fingerprint(call.project_root)
                receipt = self._approval_store.record_envelope_result(
                    envelope_lease,
                    project_fingerprint=resulting_fingerprint,
                    outcome="completed" if child.status is TaskStatus.completed else "failed",
                )
                if receipt is not None:
                    self._tasks.append(task_id, TaskEventDraft(
                        event_type="agent.approval_receipt",
                        payload=receipt.model_dump(mode="json"),
                    ))
            if child.status in {TaskStatus.running, TaskStatus.cancel_requested}:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.blocked",
                        payload={
                            "reason": "child outcome requires reconciliation",
                            "child_task_id": child_id,
                            "step_id": step_id,
                        },
                    ),
                )
                return self._tasks.get(task_id)
            if child.status is not TaskStatus.completed:
                if any(event.event_type == "task.permission_required" for event in child.events):
                    permission = next(
                        event for event in reversed(child.events)
                        if event.event_type == "task.permission_required"
                    )
                    self._tasks.append(
                        task_id,
                        TaskEventDraft(
                            event_type="agent.approval_required",
                            payload={
                                "child_task_id": child_id, "step_id": step_id,
                                "proposal_id": permission.payload.get("proposal_id"),
                                "call_digest": permission.payload.get("call_digest"),
                                "expires_at": permission.payload.get("expires_at"),
                                "batch_id": batch_id,
                                "batch_ordinal": batch_ordinal,
                            },
                        ),
                    )
                    return self._tasks.get(task_id)
                failure = FailureNormalizer.normalize(
                    capability_id=call.capability_id,
                    operation=call.operation,
                    status=child.status.value,
                    events=child.events,
                )
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.action_failed",
                        payload={
                            "child_task_id": child_id,
                            "step_id": step_id,
                            "criterion_id": criterion_id,
                            "attempt": criterion_attempts + 1,
                            "code": failure.code,
                            "safe_summary": failure.safe_summary,
                            "failure_signature": failure.signature,
                            "call_digest": call_digest,
                            "project_fingerprint": project_fingerprint,
                            "batch_id": batch_id,
                            "batch_ordinal": batch_ordinal,
                        },
                    ),
                )
                if isinstance(batch_id, str) and isinstance(batch_ordinal, int):
                    self._tasks.append(task_id, TaskEventDraft(
                        event_type="agent.preflight_call_finished",
                        payload={
                            "batch_id": batch_id, "ordinal": batch_ordinal,
                            "outcome": "failed", "child_task_id": child_id,
                        },
                    ))
                    self._tasks.append(task_id, TaskEventDraft(
                        event_type="agent.preflight_aborted",
                        payload={"batch_id": batch_id, "failed_ordinal": batch_ordinal},
                    ))
                    if isinstance(envelope_id, str) and self._approval_store is not None:
                        self._approval_store.revoke_envelope(envelope_id)
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.phase_changed",
                        payload={"phase": "diagnosing", "criterion_id": criterion_id},
                    ),
                )
                continue
            self._tasks.append(
                task_id,
                TaskEventDraft(
                    event_type="agent.action_completed",
                    payload={
                        "capability_id": call.capability_id,
                        "operation": call.operation,
                        "call_digest": call_digest,
                        "child_task_id": child_id,
                        "step_id": step_id,
                        "project_fingerprint": self._project_fingerprint(call.project_root),
                        "batch_id": batch_id,
                        "batch_ordinal": batch_ordinal,
                    },
                ),
            )
            if isinstance(batch_id, str) and isinstance(batch_ordinal, int):
                self._tasks.append(task_id, TaskEventDraft(
                    event_type="agent.preflight_call_finished",
                    payload={
                        "batch_id": batch_id, "ordinal": batch_ordinal,
                        "outcome": "completed", "child_task_id": child_id,
                    },
                ))
            if resolved is not None:
                reader, target_path = resolved
                self.context.capture_project(
                    root.thread_id,
                    task_id,
                    reader,
                    target_path=target_path if isinstance(target_path, str) else ".",
                    prioritize_references_in=goal.objective,
                )
            context = self.context.assemble(root.thread_id, task_id, PLANNER_CONTEXT_BUDGET)
            if (
                isinstance(batch_id, str) and isinstance(batch_ordinal, int)
                and isinstance(batch_size, int) and batch_ordinal + 1 < batch_size
            ):
                continue
            if isinstance(batch_id, str):
                self._tasks.append(task_id, TaskEventDraft(
                    event_type="agent.preflight_completed",
                    payload={"batch_id": batch_id, "call_count": batch_size or 0},
                ))
            completed = await self._complete_if_verified(
                task_id, goal, root_command, context, record_failure=True
            )
            if completed is not None:
                return completed

    async def _next_planned_call(self, task_id, goal, root, context):
        completed_batches = {
            event.payload.get("batch_id")
            for event in root.events
            if event.event_type in {"agent.preflight_completed", "agent.preflight_aborted"}
        }
        preflight = next(
            (
                event for event in reversed(root.events)
                if event.event_type == "agent.preflight_planned"
                and event.payload.get("batch_id") not in completed_batches
            ),
            None,
        )
        if preflight is None:
            plan_batch = getattr(self._planner, "plan_batch", None)
            if not callable(plan_batch):
                call = await self._planner.plan(context)
                return None if call is None else (call, None, None, None, None)
            calls = tuple(await plan_batch(context))
            if not calls:
                return None
            prepared = tuple(self._core.prepare_capability_call(root.project_id, call) for call in calls)
            project_roots = {call.project_root for call in prepared}
            if len(project_roots) != 1:
                raise ValueError("one approval preflight cannot cross project roots")
            batch_number = 1 + sum(
                event.event_type == "agent.preflight_planned" for event in root.events
            )
            batch_id = f"preflight-{task_id}-{batch_number}"
            principal, _principal_scopes = self._principal_context(root)
            eligible = tuple(
                call for call in prepared
                if self._core.approval_required(root.project_id, call, principal=principal)
                and not requires_separate_approval(call)
            )
            envelope = None
            if eligible:
                if self._approval_store is None:
                    raise RuntimeError("batch approval requires an approval store")
                project_root = prepared[0].project_root
                envelope = self._approval_store.propose_envelope(
                    principal=principal, project_id=root.project_id, task_id=task_id,
                    task_revision=goal.revision, calls=eligible,
                    project_fingerprint=self._project_fingerprint(project_root),
                )
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.preflight_planned",
                payload={
                    "batch_id": batch_id,
                    "task_revision": goal.revision,
                    "calls": [call.model_dump(mode="json") for call in prepared],
                    "envelope_id": None if envelope is None else envelope.envelope_id,
                },
            ))
            preflight = next(
                event for event in reversed(self._tasks.get(task_id).events)
                if event.event_type == "agent.preflight_planned"
                and event.payload.get("batch_id") == batch_id
            )

        batch_id = preflight.payload.get("batch_id")
        raw_calls = preflight.payload.get("calls")
        if not isinstance(batch_id, str) or not isinstance(raw_calls, (list, tuple)):
            raise ValueError("agent preflight is invalid")
        calls = tuple(CapabilityCall.model_validate(value) for value in raw_calls)
        finished = {
            event.payload.get("ordinal")
            for event in root.events
            if event.event_type == "agent.preflight_call_finished"
            and event.payload.get("batch_id") == batch_id
        }
        ordinal = next((index for index in range(len(calls)) if index not in finished), None)
        if ordinal is None:
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.preflight_completed",
                payload={"batch_id": batch_id, "call_count": len(calls)},
            ))
            return None
        envelope_id = preflight.payload.get("envelope_id")
        if isinstance(envelope_id, str):
            if self._approval_store is None:
                raise RuntimeError("agent preflight approval store is unavailable")
            envelope = self._approval_store.get_envelope(envelope_id)
            if envelope.status == "pending":
                principal, _principal_scopes = self._principal_context(root)
                current_call = calls[ordinal]
                if (
                    self._core.approval_required(root.project_id, current_call, principal=principal)
                    and not requires_separate_approval(current_call)
                ):
                    already_requested = any(
                        event.event_type == "agent.approval_required"
                        and event.payload.get("envelope_id") == envelope.envelope_id
                        for event in root.events
                    )
                    if not already_requested:
                        self._tasks.append(task_id, TaskEventDraft(
                            event_type="agent.approval_required",
                            payload={
                                "batch_id": batch_id,
                                "envelope_id": envelope.envelope_id,
                                "task_revision": goal.revision,
                                "project_root": current_call.project_root,
                                "project_fingerprint": envelope.project_fingerprint,
                                "expires_at": envelope.expires_at.isoformat(),
                                "call_count": len(envelope.calls),
                                "calls": [
                                    {
                                        "ordinal": item.ordinal,
                                        "capability_id": item.capability_id,
                                        "operation": item.operation,
                                        "target_path": item.target_path,
                                        "call_digest": item.call_digest,
                                    }
                                    for item in envelope.calls
                                ],
                            },
                        ))
                    return _WAITING_FOR_APPROVAL
            elif envelope.status not in {"approved", "consumed"}:
                raise PermissionError(f"approval envelope is {envelope.status}")
        return calls[ordinal], batch_id, ordinal, len(calls), envelope_id

    @staticmethod
    def _has_pending_preflight(root) -> bool:
        completed = {
            event.payload.get("batch_id")
            for event in root.events
            if event.event_type in {"agent.preflight_completed", "agent.preflight_aborted"}
        }
        return any(
            event.event_type == "agent.preflight_planned"
            and event.payload.get("batch_id") not in completed
            for event in root.events
        )

    @staticmethod
    def _principal_context(root) -> tuple[str, tuple[str, ...]]:
        binding = next(
            (event for event in root.events if event.event_type == "task.principal_bound"),
            None,
        )
        if binding is None:
            return "user", ()
        principal = binding.payload.get("principal")
        scopes = binding.payload.get("principal_scopes", ())
        if not isinstance(principal, str) or not principal:
            raise ValueError("agent task principal binding is invalid")
        if not isinstance(scopes, (list, tuple)) or not all(isinstance(item, str) for item in scopes):
            raise ValueError("agent task principal scopes are invalid")
        return principal, tuple(scopes)

    async def _complete_if_verified(
        self, task_id, goal, root_command, context, *, record_failure: bool
    ):
        report = await self._verifier.verify(goal, self._tasks.get(task_id), context)
        project_root = None
        for source in reversed(context.sources):
            if source.kind != "project_snapshot":
                continue
            try:
                project_root = json.loads(source.content).get("project_root")
            except (json.JSONDecodeError, AttributeError):
                project_root = None
            if isinstance(project_root, str) and project_root:
                break
        try:
            self._evidence.validate(
                report,
                goal,
                root_command,
                current_project_fingerprint=self._project_fingerprint(project_root),
            )
        except StaleEvidence as error:
            if record_failure:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.verification_failed",
                        payload={"reason": str(error), "report_id": report.report_id},
                    ),
                )
            return None
        if not report.satisfied:
            if record_failure:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="agent.verification_failed",
                        payload=report.model_dump(mode="json"),
                    ),
                )
            return None
        self._tasks.append(
            task_id,
            TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "verifying"}),
        )
        self._tasks.append(
            task_id,
            TaskEventDraft(
                event_type="agent.verification_completed",
                payload=report.model_dump(mode="json"),
            ),
        )
        self._tasks.append(
            task_id,
            TaskEventDraft(
                event_type="agent.verified",
                payload={"report_id": report.report_id, "goal_revision": goal.revision},
            ),
        )
        self._tasks.append(task_id, TaskEventDraft(event_type="task.completed"))
        return self._tasks.get(task_id)

    def steer(self, task_id: str, user_input: str):
        return self._tasks.append(task_id, TaskEventDraft(event_type="task.steered", payload={"input": user_input}))

    async def resume(self, task_id: str):
        return await self.run(task_id)
