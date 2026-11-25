import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5, uuid7

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.adapters import CapabilityExecutionError
from web_app.core.agent_runtime import AgentRuntime
from web_app.core.agent_services import EventEvidenceVerifier
from web_app.core.approval import ApprovalStore
from web_app.core.context_service import ContextService
from web_app.core.contracts import (
    CompletionCriterion,
    CriterionKind,
    CriterionStatus,
    EvidenceRef,
    ExecutionMode,
    GoalSpec,
    TaskCommand,
    TaskEventDraft,
    TaskStatus,
    VerificationReport,
)
from web_app.core.memory import MemoryStore
from web_app.core.policy import PolicyService
from web_app.core.project_intelligence import ProjectReader
from web_app.core.project_registry import ProjectRegistry
from web_app.core.router import ExecutionCandidate, ExecutionRouter, RouteConsentRequired
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    async def execute(self, call, context):
        self.calls.append(call)
        yield AdapterEvent(event_type="capability.result", payload={"operation": call.operation})


class FailingAdapter:
    def __init__(self):
        self.calls = []

    async def execute(self, call, context):
        self.calls.append(call)
        raise CapabilityExecutionError("tests_failed", "focused tests failed")
        yield


class MutatingAdapter:
    def __init__(self, path):
        self.path = path

    async def execute(self, call, context):
        self.path.write_text("answer = 43\n", encoding="utf-8")
        yield AdapterEvent(event_type="capability.result", payload={"operation": call.operation})


class DeterministicPlanner:
    def __init__(self, calls):
        self.calls = list(calls)

    async def plan(self, context):
        return self.calls.pop(0) if self.calls else None


class BatchPlanner:
    def __init__(self, calls):
        self.calls = tuple(calls)
        self.planned = False

    async def plan_batch(self, context):
        if self.planned:
            return ()
        self.planned = True
        return self.calls

    async def plan(self, context):
        raise AssertionError("batch-capable planners must use one preflight")


class DeterministicVerifier:
    def __init__(self, satisfied=True, project_fingerprint=None):
        self.satisfied = satisfied
        self.project_fingerprint = project_fingerprint
        self.calls = []

    async def verify(self, goal, task, context):
        self.calls.append((goal, task, context))
        status = CriterionStatus.passed if self.satisfied else CriterionStatus.failed
        evidence = ()
        if self.satisfied:
            fingerprint = (
                self.project_fingerprint()
                if callable(self.project_fingerprint)
                else self.project_fingerprint or "sha256:" + "1" * 64
            )
            evidence = tuple(
                EvidenceRef(
                    evidence_id=f"evidence-{criterion.criterion_id}", task_id=task.task_id,
                    project_id=task.project_id, goal_id=goal.goal_id, goal_revision=goal.revision,
                    criterion_id=criterion.criterion_id, source_ref=f"task:{task.task_id}",
                    project_fingerprint=fingerprint, observed_at=datetime.now(UTC),
                )
                for criterion in goal.criteria
            )
        return VerificationReport(
            report_id=f"report-{task.task_id}", task_id=task.task_id, project_id=task.project_id,
            goal_id=goal.goal_id, goal_revision=goal.revision,
            expected_criterion_ids=tuple(item.criterion_id for item in goal.criteria),
            results={item.criterion_id: status for item in goal.criteria},
            evidence=evidence, verified_at=datetime.now(UTC),
        )


class SequencedVerifier(DeterministicVerifier):
    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = iter(outcomes)

    async def verify(self, goal, task, context):
        self.satisfied = next(self.outcomes)
        return await super().verify(goal, task, context)


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_lesson_activation_requires_ready_service_identity(self):
        class Gate:
            def automatic_lesson_activation_ready(self):
                return True

        runtime = AgentRuntime(
            None, None, None, None, None, lambda _root: "", verifier_identity=Gate()
        )
        unavailable = AgentRuntime(None, None, None, None, None, lambda _root: "")
        self.assertTrue(runtime.automatic_lesson_activation_ready())
        self.assertFalse(unavailable.automatic_lesson_activation_ready())

    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tasks = TaskStore(self.root / "tasks.sqlite")
        self.policy = PolicyService(self.root / "policy.sqlite")
        self.memory = MemoryStore(self.root / "memory.sqlite")
        self.projects = ProjectRegistry(self.root / "projects.sqlite")
        self.projects.register(self.root, project_id="project-1")

    async def asyncTearDown(self):
        self.memory.close()
        self.policy.close()
        self.tasks.close()
        self.projects.close()
        self.temporary.cleanup()

    def create_root_task(self, *, accepted=True, project_root=None, objective="Complete the requested coding task"):
        task_id = str(uuid7())
        goal = GoalSpec(
            goal_id="goal-1", revision=1, objective=objective,
            criteria=(CompletionCriterion(
                criterion_id="verified", kind=CriterionKind.project_state,
                description="The resulting project state is verified",
            ),),
            accepted=accepted,
        )
        payload = {"goal_spec": goal.model_dump(mode="json")}
        if project_root is not None:
            payload["project_root"] = str(project_root)
        project_id = "project-1" if project_root is None else self.projects.register(project_root).project_id
        command = TaskCommand(
            command_id=str(uuid7()), task_id=task_id, thread_id="thread-1", project_id=project_id,
            command_type="agent.run", payload=payload,
        )
        self.tasks.create(command)
        return task_id

    async def test_agent_loop_submits_every_action_through_core_service(self):
        adapter = RecordingAdapter()
        core = CoreService(self.tasks, self.policy, {"project.read": adapter, "project.patch": adapter, "test.run": adapter}, project_roots=self.projects)
        calls = [
            CapabilityCall(capability_id="project.read", operation="read", project_root=str(self.root)),
            CapabilityCall(capability_id="project.patch", operation="replace", project_root=str(self.root)),
            CapabilityCall(capability_id="test.run", operation="test", project_root=str(self.root)),
        ]
        class VerifyAfterThreeActions(DeterministicVerifier):
            async def verify(inner_self, goal, task, context):
                inner_self.satisfied = sum(
                    event.event_type == "agent.action_completed" for event in task.events
                ) >= 3
                return await super().verify(goal, task, context)

        runtime = AgentRuntime(
            self.tasks, core, ContextService(self.tasks, self.memory), DeterministicPlanner(calls),
            VerifyAfterThreeActions(), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()
        for call in calls[1:]:
            self.policy.grant("user", "project-1", call, scope="project")

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.completed)
        self.assertEqual([call.capability_id for call in adapter.calls], ["project.read", "project.patch", "test.run"])
        children = self.tasks.children(task_id)
        self.assertEqual(len(children), 3)
        self.assertTrue(all(child.status is TaskStatus.completed for child in children))
        self.assertEqual(
            [event.event_type for event in result.events if event.event_type.startswith("agent.")],
            [
                "agent.goal_registered", "agent.started", "agent.phase_changed",
                "agent.step_planned", "agent.action_completed", "agent.verification_failed",
                "agent.step_planned", "agent.action_completed", "agent.verification_failed",
                "agent.step_planned", "agent.action_completed",
                "agent.phase_changed", "agent.verification_completed", "agent.verified",
            ],
        )

    async def test_planner_rejection_never_reserves_an_executable_child_command(self):
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {"project.read": RecordingAdapter()}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            DeterministicPlanner([
                CapabilityCall(capability_id="unregistered.planner", operation="read", project_root=str(self.root)),
            ]),
            DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        with self.assertRaisesRegex(LookupError, "unknown capability"):
            await runtime.run(task_id)

        self.assertEqual(self.tasks.children(task_id), ())
        self.assertNotIn("agent.step_planned", [event.event_type for event in self.tasks.get(task_id).events])

    async def test_planner_child_command_is_server_canonical_before_atomic_reservation(self):
        projects = ProjectRegistry(self.root / "projects.sqlite")
        projects.register(self.root, project_id="project-1")
        (self.root / "alias").mkdir()
        adapter = RecordingAdapter()
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {"project.read": adapter}, project_roots=projects),
            ContextService(self.tasks, self.memory),
            DeterministicPlanner([
                CapabilityCall(
                    capability_id="project.read", operation="read", project_root=str(self.root / "alias" / ".."),
                ),
            ]),
            DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()
        try:
            await runtime.run(task_id)
            child = self.tasks.children(task_id)[0]
            command = self.tasks.command(child.task_id)
            self.assertEqual(command.payload["operation"], "read")
            self.assertEqual(command.payload["project_root"], str(self.root.resolve()))
        finally:
            projects.close()

    async def test_planner_context_is_bounded_for_local_model_stability(self):
        observed = []

        class RecordingPlanner:
            async def plan(_self, context):
                observed.append(context)
                return None

        task_id = self.create_root_task()
        self.memory.add(
            "thread-1", "workspace_context", "evidence " * 2_000,
            source_ref="workspace-context:test",
        )
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            RecordingPlanner(),
            DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )

        await runtime.run(task_id)

        self.assertEqual(len(observed), 1)
        self.assertTrue(all(len(context.text) <= 2_000 for context in observed))

    async def test_satisfied_verification_completes_without_a_second_planner_call(self):
        adapter = RecordingAdapter()
        call = CapabilityCall(
            capability_id="project.read", operation="read", project_root=str(self.root)
        )

        class OneShotPlanner:
            def __init__(self):
                self.calls = 0

            async def plan(inner_self, _context):
                inner_self.calls += 1
                return call if inner_self.calls == 1 else None

        planner = OneShotPlanner()
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {"project.read": adapter}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            planner,
            DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.completed)
        self.assertEqual(planner.calls, 1)

    async def test_steering_is_durable_and_visible_to_the_next_plan(self):
        adapter = RecordingAdapter()
        planner = DeterministicPlanner([])
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.read": adapter}, project_roots=self.projects),
            ContextService(self.tasks, self.memory), planner, DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        runtime.steer(task_id, "inspect configuration first")
        context = runtime.context.assemble("thread-1", task_id, 4096)

        self.assertIn("inspect configuration first", context.text)
        self.assertTrue(any(source.kind == "task_event" for source in context.sources))

    async def test_runtime_captures_trusted_project_context_before_planning(self):
        project = self.root / "project"
        project.mkdir()
        (project / "AGENTS.md").write_text("Use project evidence.", encoding="utf-8")
        (project / "module.py").write_text("PROJECT_FACT = 42\n", encoding="utf-8")
        verifier = DeterministicVerifier()
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            DeterministicPlanner([]),
            verifier,
            lambda _root: "sha256:" + "1" * 64,
            project_reader_resolver=lambda command: (ProjectReader(project), "."),
        )
        task_id = self.create_root_task(project_root=project)

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.completed)
        planned_context = verifier.calls[0][2]
        self.assertIn("Use project evidence.", planned_context.text)
        self.assertIn("PROJECT_FACT = 42", planned_context.text)
        self.assertTrue(any(source.kind == "project_snapshot" for source in planned_context.sources))

    async def test_runtime_prioritizes_a_goal_referenced_file_within_planner_budget(self):
        project = self.root / "project"
        project.mkdir()
        target = project / "config.json"
        target.write_text(
            '{"schema_version":1,"source":"exact-source","feature_enabled":false}\n',
            encoding="utf-8",
        )
        for index in range(12):
            (project / f"noise-{index:02}.txt").write_text("noise " * 80, encoding="utf-8")
        observed = []

        class RecordingPlanner:
            async def plan(_self, context):
                observed.append(context)
                return None

        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            RecordingPlanner(),
            DeterministicVerifier(satisfied=False),
            lambda _root: ProjectReader(project).fingerprint(),
            project_reader_resolver=lambda _command: (ProjectReader(project), "."),
        )
        task_id = self.create_root_task(
            project_root=project,
            objective=(
                "Edit only config.json. Preserve schema_version and source exactly. "
                "Change feature_enabled from false to true."
            ),
        )

        await runtime.run(task_id)

        self.assertEqual(len(observed), 3)
        self.assertTrue(all('"source":"exact-source"' in item.text for item in observed))
        self.assertTrue(all(len(item.text) <= 3_000 for item in observed))

    def test_project_fingerprint_is_independent_of_context_priority_order(self):
        project = self.root / "project"
        project.mkdir()
        (project / "a.txt").write_text("a", encoding="utf-8")
        (project / "b.txt").write_text("b", encoding="utf-8")
        reader = ProjectReader(project)
        files = reader.files()

        self.assertEqual(reader.fingerprint(files), reader.fingerprint(tuple(reversed(files))))

    async def test_mutation_refreshes_project_context_before_verification(self):
        project = self.root / "project"
        project.mkdir()
        target = project / "module.py"
        target.write_text("answer = 42\n", encoding="utf-8")
        adapter = MutatingAdapter(target)
        context = ContextService(self.tasks, self.memory)
        call = CapabilityCall(
            capability_id="project.patch", operation="replace",
            project_root=str(project), target_path=str(target),
        )
        self.policy.grant("user", self.projects.register(project).project_id, call, scope="project")
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {"project.patch": adapter}, project_roots=self.projects),
            context,
            DeterministicPlanner([call]),
            EventEvidenceVerifier(),
            lambda _root: ProjectReader(project).fingerprint(),
            project_reader_resolver=lambda _command: (ProjectReader(project), "."),
        )
        task_id = self.create_root_task(project_root=project)

        result = await runtime.run(task_id)

        self.assertEqual(
            result.status,
            TaskStatus.completed,
            [event.model_dump(mode="json") for event in result.events],
        )
        self.assertIn("answer = 43", context.assemble("thread-1", task_id, 32_000).text)

    async def test_cancel_requested_stops_before_next_agent_action(self):
        adapter = RecordingAdapter()
        task_id = self.create_root_task()

        class CancellingPlanner:
            async def plan(_self, _context):
                self.tasks.request_cancel(task_id)
                return CapabilityCall(
                    capability_id="project.patch", operation="replace", project_root=str(self.root)
                )

        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.patch": adapter}, project_roots=self.projects),
            ContextService(self.tasks, self.memory), CancellingPlanner(),
            DeterministicVerifier(), lambda _root: "sha256:" + "1" * 64,
        )

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.cancelled)
        self.assertEqual(adapter.calls, [])

    async def test_approved_child_can_resume_the_agent_root(self):
        adapter = RecordingAdapter()
        call = CapabilityCall(
            capability_id="component.install", operation="install",
            project_root=str(self.root), target_path=str(self.root / "file.py"),
        )
        core = CoreService(self.tasks, self.policy, {"component.install": adapter}, project_roots=self.projects)
        runtime = AgentRuntime(
            self.tasks, core, ContextService(self.tasks, self.memory),
            DeterministicPlanner([call]), DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        waiting = await runtime.run(task_id)
        approval = next(event for event in waiting.events if event.event_type == "agent.approval_required")
        await core.approve(approval.payload["child_task_id"])
        completed = await runtime.resume(task_id)

        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(len(adapter.calls), 1)

    async def test_one_envelope_approves_two_exact_agent_actions_and_emits_receipt(self):
        adapter = RecordingAdapter()
        calls = (
            CapabilityCall(
                capability_id="project.patch", operation="replace", project_root=str(self.root),
                target_path="one.py", arguments={"content": "one = 1\n"},
            ),
            CapabilityCall(
                capability_id="project.patch", operation="replace", project_root=str(self.root),
                target_path="two.py", arguments={"content": "two = 2\n"},
            ),
        )
        approvals = ApprovalStore(self.root / "envelope-approvals.sqlite")
        fingerprint = lambda _root=None: "sha256:" + "1" * 64
        core = CoreService(
            self.tasks, self.policy, {"project.patch": adapter},
            approval_store=approvals, project_fingerprint=fingerprint, project_roots=self.projects,
        )
        runtime = AgentRuntime(
            self.tasks, core, ContextService(self.tasks, self.memory), BatchPlanner(calls),
            DeterministicVerifier(), fingerprint, approval_store=approvals,
        )
        core._agent_runner = runtime.run
        task_id = self.create_root_task()
        self.tasks.append(task_id, TaskEventDraft(
            event_type="task.principal_bound",
            payload={"principal": "administrator-1", "principal_scopes": ["agent.launch"]},
        ))

        try:
            waiting = await runtime.run(task_id)
            approval = next(
                event for event in waiting.events if event.event_type == "agent.approval_required"
            )
            self.assertEqual(approval.payload["call_count"], 2)
            self.assertEqual(adapter.calls, [])

            completed = await core.approve(
                task_id, principal="administrator-1", principal_scopes=("agent.launch",),
                envelope_id=approval.payload["envelope_id"],
            )
        finally:
            approvals.close()

        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(adapter.calls, list(calls))
        receipts = [
            event for event in completed.events if event.event_type == "agent.approval_receipt"
        ]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].payload["outcomes"], ("completed", "completed"))
        self.assertEqual(
            len([event for event in completed.events if event.event_type == "agent.approval_required"]),
            1,
        )

    async def test_exact_approval_ignores_runtime_churn_and_applies_requested_edit(self):
        project = self.root / "project"
        runtime_state = project / ".runtime"
        runtime_state.mkdir(parents=True)
        target = project / "config.json"
        target.write_text(
            '{"schema_version":1,"source":"exact-source","feature_enabled":false}\n',
            encoding="utf-8",
        )
        runtime_log = runtime_state / "server.log"
        runtime_log.write_text("started\n", encoding="utf-8")

        class JsonMutatingAdapter:
            def __init__(inner_self):
                inner_self.calls = []

            async def execute(inner_self, call, context):
                inner_self.calls.append(call)
                target.write_text(call.arguments["content"], encoding="utf-8")
                yield AdapterEvent(event_type="capability.result", payload={"operation": call.operation})

        adapter = JsonMutatingAdapter()
        replacement = '{"schema_version":1,"source":"exact-source","feature_enabled":true}\n'
        call = CapabilityCall(
            capability_id="project.patch", operation="replace",
            project_root=str(project), target_path=str(target), arguments={"content": replacement},
        )
        fingerprint = lambda _root=None: ProjectReader(project).fingerprint()
        approvals = ApprovalStore(self.root / "approvals.sqlite")
        core = CoreService(
            self.tasks, self.policy, {"project.patch": adapter},
            approval_store=approvals, project_fingerprint=fingerprint, project_roots=self.projects,
        )
        runtime = AgentRuntime(
            self.tasks, core, ContextService(self.tasks, self.memory),
            DeterministicPlanner([call]), DeterministicVerifier(project_fingerprint=fingerprint),
            fingerprint,
        )
        task_id = self.create_root_task(project_root=project)

        try:
            waiting = await runtime.run(task_id)
            approval = next(
                event for event in waiting.events if event.event_type == "agent.approval_required"
            )
            runtime_log.write_text("started\nrequest completed\n", encoding="utf-8")

            await core.approve(
                approval.payload["child_task_id"],
                proposal_id=approval.payload["proposal_id"],
            )
            completed = await runtime.resume(task_id)
        finally:
            approvals.close()

        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(target.read_text(encoding="utf-8"), replacement)
        self.assertEqual(adapter.calls, [call])

    async def test_identical_successful_action_is_verified_without_executing_twice(self):
        adapter = RecordingAdapter()
        call = CapabilityCall(
            capability_id="project.read", operation="read",
            project_root=str(self.root), target_path=str(self.root / "file.py"),
        )
        self.policy.grant("user", "project-1", call, scope="project")
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {"project.read": adapter}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            DeterministicPlanner([call, call]),
            DeterministicVerifier(),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        completed = await runtime.run(task_id)

        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(adapter.calls, [call])
        event_types = [event.event_type for event in completed.events]
        self.assertIn("agent.verification_completed", event_types)
        self.assertIn("agent.verified", event_types)

    async def test_restart_does_not_treat_unresolved_running_child_as_failed(self):
        call = CapabilityCall(
            capability_id="project.read", operation="read", project_root=str(self.root)
        )
        task_id = self.create_root_task()
        child_id = str(uuid5(NAMESPACE_URL, f"json-codr:{task_id}:step-1:task"))
        child_command = TaskCommand(
            command_id=str(uuid5(NAMESPACE_URL, f"json-codr:{task_id}:step-1:command")),
            task_id=child_id, thread_id="thread-1", project_id="project-1",
            parent_task_id=task_id, command_type="project.read",
            payload=call.model_dump(mode="json"),
        )
        self.tasks.create(child_command)
        self.tasks.append(child_id, TaskEventDraft(event_type="task.started"))
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.read": RecordingAdapter()}, project_roots=self.projects),
            ContextService(self.tasks, self.memory), DeterministicPlanner([call]),
            DeterministicVerifier(), lambda _root: "sha256:" + "1" * 64,
        )

        result = await runtime.run(task_id)

        self.assertNotIn("agent.action_failed", [event.event_type for event in result.events])
        blocked = next(event for event in result.events if event.event_type == "agent.blocked")
        self.assertEqual(blocked.payload["reason"], "child outcome requires reconciliation")

    async def test_planner_silence_cannot_complete_when_verification_fails(self):
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {}, project_roots=self.projects),
            ContextService(self.tasks, self.memory), DeterministicPlanner([]),
            DeterministicVerifier(satisfied=False), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.pending)
        self.assertNotIn("task.completed", [event.event_type for event in result.events])
        self.assertIn("agent.verification_failed", [event.event_type for event in result.events])

    async def test_failed_verification_returns_to_planning(self):
        adapter = RecordingAdapter()
        call = CapabilityCall(
            capability_id="project.read", operation="read", project_root=str(self.root)
        )
        planner = DeterministicPlanner([None, call, None])
        runtime = AgentRuntime(
            self.tasks,
            CoreService(self.tasks, self.policy, {"project.read": adapter}, project_roots=self.projects),
            ContextService(self.tasks, self.memory),
            planner,
            SequencedVerifier([False, True]),
            lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.completed)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(
            sum(event.event_type == "agent.verification_failed" for event in result.events),
            1,
        )

    async def test_unaccepted_generated_goal_blocks_before_mutation(self):
        adapter = RecordingAdapter()
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.patch": adapter}),
            ContextService(self.tasks, self.memory),
            DeterministicPlanner([CapabilityCall(
                capability_id="project.patch", operation="replace", project_root=str(self.root)
            )]),
            DeterministicVerifier(), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task(accepted=False)

        result = await runtime.run(task_id)

        self.assertEqual(adapter.calls, [])
        self.assertIn("agent.goal_acceptance_required", [event.event_type for event in result.events])

    async def test_unchanged_failed_action_is_not_executed_twice(self):
        adapter = FailingAdapter()
        call = CapabilityCall(
            capability_id="test.run", operation="test", project_root=str(self.root)
        )
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"test.run": adapter}, project_roots=self.projects),
            ContextService(self.tasks, self.memory), DeterministicPlanner([call, call]),
            DeterministicVerifier(), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()
        self.policy.grant("user", "project-1", call, scope="project")

        result = await runtime.run(task_id)

        self.assertEqual(len(adapter.calls), 1)
        self.assertIn("agent.action_failed", [event.event_type for event in result.events])
        blocked = next(event for event in result.events if event.event_type == "agent.blocked")
        self.assertEqual(blocked.payload["reason"], "unchanged repair loop")

    def test_context_compaction_preserves_provenance_to_original_events(self):
        task_id = self.create_root_task()
        first = self.tasks.append(task_id, TaskEventDraft(event_type="task.steered", payload={"input": "keep this"}))
        self.memory.add("thread-1", "note", "persistent project fact", source_ref="artifact:fact-1")
        context = ContextService(self.tasks, self.memory)

        compacted = context.compact("thread-1")
        bundle = context.assemble("thread-1", task_id, 4096)

        self.assertIn(f"event:{first.event_id}", compacted.source_refs)
        self.assertIn("artifact:fact-1", compacted.source_refs)
        self.assertIn("persistent project fact", bundle.text)
        self.assertTrue(all(source.source_ref for source in bundle.sources))

    def test_router_prefers_verified_compatible_route_and_requires_boundary_consent(self):
        router = ExecutionRouter([
            ExecutionCandidate(
                route_id="ollama-cpu", model_id="qwen3:4b", mode=ExecutionMode.native,
                compatible=True, verified=True, privacy_boundary="local", cost_boundary="local", priority=20,
            ),
            ExecutionCandidate(
                route_id="cloud", model_id="cloud-model", mode=ExecutionMode.brokered,
                compatible=True, verified=True, privacy_boundary="cloud", cost_boundary="paid", priority=1,
            ),
        ])

        route = router.resolve({"model_id": "missing"}, {"privacy_boundary": "local", "cost_boundary": "local"})
        self.assertEqual(route.effective_model_id, "qwen3:4b")
        self.assertEqual(route.requested_model_id, "missing")
        self.assertTrue(route.fallback_used)
        with self.assertRaises(RouteConsentRequired):
            router.resolve(
                {"model_id": "cloud-model"},
                {"privacy_boundary": "local", "cost_boundary": "local"},
            )


if __name__ == "__main__":
    unittest.main()
