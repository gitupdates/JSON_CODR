from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from web_app.core.agent_verification import EvidenceResolver, FailureNormalizer, StaleEvidence
from web_app.core.canonical import canonical_digest
from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import GoalSpec, PlanRevision, TaskCommand, TaskEventDraft, TaskStatus
from web_app.core.policy import PolicySnapshot


class AgentRuntime:
    def __init__(
        self, task_store, core_service, context, planner, verifier, project_fingerprint,
        *, plan_service=None, policy_snapshot: PolicySnapshot | None = None,
    ) -> None:
        self._tasks = task_store
        self._core = core_service
        self.context = context
        self._planner = planner
        self._verifier = verifier
        self._project_fingerprint = project_fingerprint
        self._evidence = EvidenceResolver()
        self._plan_service = plan_service
        self._policy_snapshot = policy_snapshot

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
        if self._plan_service is not None:
            return await self._run_guided(task_id, goal, root_command)
        while True:
            root = self._tasks.get(task_id)
            context = self.context.assemble(root.thread_id, task_id, 32_000)
            call = await self._planner.plan(context)
            if call is None:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "verifying"}),
                )
                report = await self._verifier.verify(goal, self._tasks.get(task_id), context)
                try:
                    self._evidence.validate(
                        report,
                        goal,
                        root_command,
                        current_project_fingerprint=self._project_fingerprint(None),
                    )
                except StaleEvidence as error:
                    self._tasks.append(
                        task_id,
                        TaskEventDraft(
                            event_type="agent.verification_failed",
                            payload={"reason": str(error), "report_id": report.report_id},
                        ),
                    )
                    return self._tasks.get(task_id)
                if not report.satisfied:
                    self._tasks.append(
                        task_id,
                        TaskEventDraft(
                            event_type="agent.verification_failed",
                            payload=report.model_dump(mode="json"),
                        ),
                    )
                    return self._tasks.get(task_id)
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
                        "child_task_id": child_id,
                        "step_id": step_id,
                        "project_fingerprint": project_fingerprint,
                    },
                ),
            )

    async def _run_guided(self, task_id: str, goal: GoalSpec, root_command: TaskCommand):
        root = self._tasks.get(task_id)
        plans = self._tasks.plans(task_id)
        if not plans:
            context = self.context.assemble(root.thread_id, task_id, 32_000)
            proposed = await self._planner.plan(context)
            if not isinstance(proposed, PlanRevision):
                raise TypeError("guided planner must return a complete PlanRevision")
            current = self._plan_service.create(task_id, proposed)
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.plan_context_bound",
                payload={
                    "plan_id": current.plan_id,
                    "plan_revision": current.revision,
                    "plan_digest": current.canonical_digest,
                    "project_fingerprint": self._project_fingerprint(None),
                    "policy_digest": None if self._policy_snapshot is None else self._policy_snapshot.canonical_digest,
                },
            ))
            self._tasks.append(
                task_id, TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "plan_review"}),
            )
            return self._tasks.get(task_id)

        current = plans[-1]
        decisions = self._tasks.plan_decisions(task_id, current.plan_id, current.revision)
        approved = any(decision.step_id is None and decision.decision == "approve" for decision in decisions)
        if not approved:
            return self._tasks.get(task_id)

        binding = next(
            (
                event for event in reversed(root.events)
                if event.event_type == "agent.plan_context_bound"
                and event.payload.get("plan_id") == current.plan_id
                and event.payload.get("plan_revision") == current.revision
            ),
            None,
        )
        current_policy_digest = None if self._policy_snapshot is None else self._policy_snapshot.canonical_digest
        if binding is None or (
            binding.payload.get("project_fingerprint") != self._project_fingerprint(None)
            or binding.payload.get("policy_digest") != current_policy_digest
        ):
            if not any(event.event_type == "agent.plan_invalidated" for event in root.events):
                self._tasks.append(task_id, TaskEventDraft(
                    event_type="agent.plan_invalidated",
                    payload={"plan_id": current.plan_id, "plan_revision": current.revision, "reason": "execution context changed"},
                ))
                self._tasks.append(
                    task_id, TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "plan_review"}),
                )
            return self._tasks.get(task_id)

        self._tasks.append(
            task_id, TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "executing"}),
        )
        project_root = str(root_command.payload.get("project_root") or ".")
        for step in current.steps:
            root = self._tasks.get(task_id)
            if any(
                event.event_type == "agent.action_completed"
                and event.payload.get("step_id") == step.step_id
                and event.payload.get("step_digest") == step.canonical_digest
                for event in root.events
            ):
                continue
            call = CapabilityCall(
                capability_id=step.capability_id,
                operation=step.operation,
                project_root=project_root,
                target_path=step.target_path,
                arguments=dict(step.arguments),
            )
            child_id = str(uuid5(NAMESPACE_URL, f"json-codr:{task_id}:{current.revision}:{step.canonical_digest}:task"))
            command_id = str(uuid5(NAMESPACE_URL, f"json-codr:{task_id}:{current.revision}:{step.canonical_digest}:command"))
            child_command = TaskCommand(
                command_id=command_id, task_id=child_id, thread_id=root.thread_id,
                project_id=root.project_id, parent_task_id=task_id,
                command_type=call.capability_id, payload=call.model_dump(mode="json"),
            )
            self._tasks.plan_step_and_create_child(
                task_id, current.plan_id, current.revision, step.step_id, child_command,
            )
            child = await self._core.submit(child_command, policy_snapshot=self._policy_snapshot)
            if any(event.event_type == "task.permission_required" for event in child.events):
                self._tasks.append(task_id, TaskEventDraft(
                    event_type="agent.approval_required",
                    payload={
                        "child_task_id": child_id, "step_id": step.step_id,
                        "step_digest": step.canonical_digest,
                    },
                ))
                return self._tasks.get(task_id)
            if child.status is not TaskStatus.completed:
                self._tasks.append(task_id, TaskEventDraft(
                    event_type="agent.action_failed",
                    payload={"child_task_id": child_id, "step_id": step.step_id, "step_digest": step.canonical_digest},
                ))
                return self._tasks.get(task_id)
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.action_completed",
                payload={
                    "capability_id": step.capability_id, "child_task_id": child_id,
                    "step_id": step.step_id, "step_digest": step.canonical_digest,
                    "project_fingerprint": self._project_fingerprint(project_root),
                },
            ))

        self._tasks.append(
            task_id, TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "verifying"}),
        )
        context = self.context.assemble(root.thread_id, task_id, 32_000)
        report = await self._verifier.verify(goal, self._tasks.get(task_id), context)
        try:
            self._evidence.validate(
                report, goal, root_command,
                current_project_fingerprint=self._project_fingerprint(None),
            )
        except StaleEvidence as error:
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.verification_failed",
                payload={"reason": str(error), "report_id": report.report_id},
            ))
            return self._tasks.get(task_id)
        if not report.satisfied:
            self._tasks.append(task_id, TaskEventDraft(
                event_type="agent.verification_failed", payload=report.model_dump(mode="json"),
            ))
            return self._tasks.get(task_id)
        self._tasks.append(task_id, TaskEventDraft(
            event_type="agent.verification_completed", payload=report.model_dump(mode="json"),
        ))
        self._tasks.append(task_id, TaskEventDraft(
            event_type="agent.verified", payload={"report_id": report.report_id, "goal_revision": goal.revision},
        ))
        self._tasks.append(task_id, TaskEventDraft(event_type="task.completed"))
        return self._tasks.get(task_id)

    def steer(self, task_id: str, user_input: str):
        return self._tasks.append(task_id, TaskEventDraft(event_type="task.steered", payload={"input": user_input}))

    async def resume(self, task_id: str):
        return await self.run(task_id)
