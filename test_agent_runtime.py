import tempfile
import unittest
from pathlib import Path
from uuid import uuid7

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.agent_runtime import AgentRuntime
from web_app.core.context_service import ContextService
from web_app.core.contracts import ExecutionMode, TaskCommand, TaskEventDraft, TaskStatus
from web_app.core.memory import MemoryStore
from web_app.core.policy import PolicyService
from web_app.core.router import ExecutionCandidate, ExecutionRouter, RouteConsentRequired
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    async def execute(self, call, context):
        self.calls.append(call)
        yield AdapterEvent(event_type="capability.result", payload={"operation": call.operation})


class DeterministicPlanner:
    def __init__(self, calls):
        self.calls = list(calls)

    async def plan(self, context):
        return self.calls.pop(0) if self.calls else None


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

    def create_root_task(self):
        task_id = str(uuid7())
        command = TaskCommand(
            command_id=str(uuid7()), task_id=task_id, thread_id="thread-1", project_id="project-1",
            command_type="agent.run", payload={},
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
            self.tasks, core, ContextService(self.tasks, self.memory), DeterministicPlanner(calls)
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
            ["agent.started", "agent.action_completed", "agent.action_completed", "agent.action_completed", "agent.verified"],
        )

    async def test_steering_is_durable_and_visible_to_the_next_plan(self):
        adapter = RecordingAdapter()
        planner = DeterministicPlanner([])
        runtime = AgentRuntime(
            self.tasks, CoreService(self.tasks, self.policy, {"project.read": adapter}),
            ContextService(self.tasks, self.memory), planner,
        )
        task_id = self.create_root_task()

        runtime.steer(task_id, "inspect configuration first")
        context = runtime.context.assemble("thread-1", task_id, 4096)

        self.assertIn("inspect configuration first", context.text)
        self.assertTrue(any(source.kind == "task_event" for source in context.sources))

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
