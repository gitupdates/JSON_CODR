from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from web_app.core.agent_verification import EvidenceResolver, FailureNormalizer, StaleEvidence
from web_app.core.canonical import canonical_digest
from web_app.core.contracts import GoalSpec, TaskCommand, TaskEventDraft, TaskStatus
from web_app.core.project_intelligence import ProjectReader


class AgentRuntime:
    def __init__(self, task_store, core_service, context, planner, verifier, project_fingerprint, project_reader_resolver=None) -> None:
        self._tasks = task_store
        self._core = core_service
        self.context = context
        self._planner = planner
        self._verifier = verifier
        self._project_fingerprint = project_fingerprint
        self._evidence = EvidenceResolver()
        self._project_reader_resolver = project_reader_resolver

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
            )
        while True:
            root = self._tasks.get(task_id)
            if root.status is TaskStatus.cancel_requested:
                self._tasks.append(task_id, TaskEventDraft(event_type="task.cancelled"))
                return self._tasks.get(task_id)
            context = self.context.assemble(root.thread_id, task_id, 32_000)
            call = await self._planner.plan(context)
            root = self._tasks.get(task_id)
            if root.status is TaskStatus.cancel_requested:
                self._tasks.append(task_id, TaskEventDraft(event_type="task.cancelled"))
                return self._tasks.get(task_id)
            if call is None:
                completed = await self._complete_if_verified(
                    task_id, goal, root_command, context, record_failure=True
                )
                return completed or self._tasks.get(task_id)
            call_digest = canonical_digest(call.model_dump(mode="json"))
            project_fingerprint = self._project_fingerprint(call.project_root)
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
            child = await self._core.submit(child_command)
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
                    self._tasks.append(
                        task_id,
                        TaskEventDraft(
                            event_type="agent.approval_required",
                            payload={"child_task_id": child_id, "step_id": step_id},
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
                        },
                    ),
                )
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
                        "child_task_id": child_id,
                        "step_id": step_id,
                        "project_fingerprint": project_fingerprint,
                    },
                ),
            )
            if resolved is not None:
                reader, target_path = resolved
                self.context.capture_project(
                    root.thread_id,
                    task_id,
                    reader,
                    target_path=target_path if isinstance(target_path, str) else ".",
                )
            refreshed_context = self.context.assemble(root.thread_id, task_id, 32_000)
            completed = await self._complete_if_verified(
                task_id, goal, root_command, refreshed_context, record_failure=False
            )
            if completed is not None:
                return completed

    async def _complete_if_verified(
        self, task_id, goal, root_command, context, *, record_failure: bool
    ):
        report = await self._verifier.verify(goal, self._tasks.get(task_id), context)
        try:
            self._evidence.validate(
                report,
                goal,
                root_command,
                current_project_fingerprint=self._project_fingerprint(None),
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
