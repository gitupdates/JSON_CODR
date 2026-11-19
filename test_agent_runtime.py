import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.adapters import CapabilityExecutionError
from web_app.core.agent_runtime import AgentRuntime
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


class DeterministicPlanner:
    def __init__(self, calls):
        self.calls = list(calls)

    async def plan(self, context):
        return self.calls.pop(0) if self.calls else None


class DeterministicVerifier:
    def __init__(self, satisfied=True):
        self.satisfied = satisfied
        self.calls = []

    async def verify(self, goal, task, context):
        self.calls.append((goal, task, context))
        status = CriterionStatus.passed if self.satisfied else CriterionStatus.failed
        evidence = ()
        if self.satisfied:
            evidence = tuple(
                EvidenceRef(
                    evidence_id=f"evidence-{criterion.criterion_id}", task_id=task.task_id,
                    project_id=task.project_id, goal_id=goal.goal_id, goal_revision=goal.revision,
                    criterion_id=criterion.criterion_id, source_ref=f"task:{task.task_id}",
                    project_fingerprint="sha256:" + "1" * 64, observed_at=datetime.now(UTC),
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


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tasks = TaskStore(self.root / "tasks.sqlite")
        self.policy = PolicyService(self.root / "policy.sqlite")
        self.memory = MemoryStore(self.root / "memory.sqlite")

    async def asyncTearDown(self):
        self.memory.close()
        self.policy.close()
        self.tasks.close()
        self.temporary.cleanup()

    def create_root_task(self, *, accepted=True, project_root=None):
        task_id = str(uuid7())
        goal = GoalSpec(
            goal_id="goal-1", revision=1, objective="Complete the requested coding task",
            criteria=(CompletionCriterion(
                criterion_id="verified", kind=CriterionKind.project_state,
                description="The resulting project state is verified",
            ),),
            accepted=accepted,
        )
        payload = {"goal_spec": goal.model_dump(mode="json")}
        if project_root is not None:
            payload["project_root"] = str(project_root)
        command = TaskCommand(
            command_id=str(uuid7()), task_id=task_id, thread_id="thread-1", project_id="project-1",
            command_type="agent.run", payload=payload,
        )
        self.tasks.create(command)
        return task_id

    async def test_agent_loop_submits_every_action_through_core_service(self):
        adapter = RecordingAdapter()
        core = CoreService(self.tasks, self.policy, {"project.read": adapter, "project.patch": adapter, "test.run": adapter})
        calls = [
            CapabilityCall(capability_id="project.read", operation="read", project_root=str(self.root)),
            CapabilityCall(capability_id="project.patch", operation="bounded_edit", project_root=str(self.root)),
            CapabilityCall(capability_id="test.run", operation="test", project_root=str(self.root)),
        ]
        runtime = AgentRuntime(
            self.tasks, core, ContextService(self.tasks, self.memory), DeterministicPlanner(calls),
            DeterministicVerifier(), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

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
                "agent.step_planned", "agent.action_completed", "agent.step_planned",
                "agent.action_completed", "agent.step_planned", "agent.action_completed",
                "agent.phase_changed", "agent.verification_completed", "agent.verified",
            ],
        )

    async def test_steering_is_durable_and_visible_to_the_next_plan(self):
        adapter = RecordingAdapter()
        planner = DeterministicPlanner([])
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.read": adapter}),
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
            CoreService(self.tasks, self.policy, {}),
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

    async def test_planner_silence_cannot_complete_when_verification_fails(self):
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {}),
            ContextService(self.tasks, self.memory), DeterministicPlanner([]),
            DeterministicVerifier(satisfied=False), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

        result = await runtime.run(task_id)

        self.assertEqual(result.status, TaskStatus.pending)
        self.assertNotIn("task.completed", [event.event_type for event in result.events])
        self.assertIn("agent.verification_failed", [event.event_type for event in result.events])

    async def test_unaccepted_generated_goal_blocks_before_mutation(self):
        adapter = RecordingAdapter()
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.patch": adapter}),
            ContextService(self.tasks, self.memory),
            DeterministicPlanner([CapabilityCall(
                capability_id="project.patch", operation="bounded_edit", project_root=str(self.root)
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
            self.tasks, CoreService(self.tasks, self.policy, {"test.run": adapter}),
            ContextService(self.tasks, self.memory), DeterministicPlanner([call, call]),
            DeterministicVerifier(), lambda _root: "sha256:" + "1" * 64,
        )
        task_id = self.create_root_task()

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
