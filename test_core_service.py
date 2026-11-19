import tempfile
import unittest
import asyncio
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
from web_app.core.contracts import TaskCommand, TaskEventDraft, TaskStatus
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class RecordingAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[CapabilityCall] = []
        self.fail = fail

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        self.calls.append(call)
        if self.fail:
            raise RuntimeError("private adapter failure")
        yield AdapterEvent(event_type="adapter.output", payload={"text": "ok"})


class BlockingAdapter:
    def __init__(self) -> None:
        self.first_consumed = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        yield AdapterEvent(event_type="adapter.delta", payload={"text": "first"})
        self.first_consumed.set()
        await self.release.wait()
        yield AdapterEvent(event_type="adapter.delta", payload={"text": "second"})


class PolicyServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = PolicyService(self.root / "policy.sqlite")

    def tearDown(self) -> None:
        self.policy.close()
        self.temporary.cleanup()

    def call(self, capability: str, operation: str, **updates: object) -> CapabilityCall:
        values = {
            "capability_id": capability,
            "operation": operation,
            "project_root": str(self.root),
            "target_path": str(self.root / "file.py"),
        }
        values.update(updates)
        return CapabilityCall(**values)

    def test_local_read_search_test_and_bounded_edit_are_automatic(self):
        for capability, operation in (
            ("project.read", "read"),
            ("project.search", "search"),
            ("project.test", "test"),
            ("project.patch", "bounded_edit"),
        ):
            decision = self.policy.evaluate("user", "project", self.call(capability, operation))
            self.assertEqual(decision.effect, PolicyEffect.allow)

    def test_escape_is_denied_and_sensitive_actions_require_approval(self):
        escaped = self.policy.evaluate(
            "user", "project", self.call("project.read", "read", target_path=str(self.root.parent / "secret"))
        )
        self.assertEqual(escaped.effect, PolicyEffect.deny)
        for operation in ("network", "install", "commit", "push", "destructive"):
            decision = self.policy.evaluate("user", "project", self.call("terminal.execute", operation))
            self.assertEqual(decision.effect, PolicyEffect.require_approval)

    def test_schedule_scoped_grant_persists_and_can_be_revoked(self):
        call = self.call("git.push", "push", schedule_id="nightly")
        self.policy.grant("user", "project", call, scope="schedule")
        reopened = PolicyService(self.root / "policy.sqlite")
        try:
            self.assertEqual(reopened.evaluate("user", "project", call).effect, PolicyEffect.allow)
            reopened.revoke("user", "project", call, scope="schedule")
            self.assertEqual(reopened.evaluate("user", "project", call).effect, PolicyEffect.require_approval)
        finally:
            reopened.close()

    def test_brokered_route_cannot_cross_privacy_or_cost_boundary(self):
        call = self.call(
            "model.generate",
            "read",
            mode="brokered",
            privacy_boundary="cloud",
            approved_privacy_boundary="local",
        )
        self.assertEqual(self.policy.evaluate("user", "project", call).effect, PolicyEffect.deny)


class CoreServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "core.sqlite")
        self.policy = PolicyService(self.root / "policy.sqlite")

    async def asyncTearDown(self) -> None:
        self.policy.close()
        self.store.close()
        self.temporary.cleanup()

    def command(self, task_id: str = "task-1", command_id: str = "command-1") -> TaskCommand:
        return TaskCommand(
            task_id=task_id,
            command_id=command_id,
            thread_id="thread-1",
            project_id="project-1",
            command_type="capability.execute",
            payload={
                "capability_id": "project.read",
                "operation": "read",
                "project_root": str(self.root),
                "target_path": str(self.root / "file.py"),
                "credential_refs": ["credential:github"],
            },
        )

    def agent_command(self, task_id: str = "agent-task", command_id: str = "agent-command") -> TaskCommand:
        return TaskCommand(
            task_id=task_id,
            command_id=command_id,
            thread_id="thread-1",
            project_id="project-1",
            command_type="agent.run",
            payload={"goal_spec": {}},
        )

    async def test_agent_command_uses_runner_once_and_replay_is_idempotent(self):
        calls = []

        async def run_agent(task_id):
            calls.append(task_id)
            self.store.append(task_id, TaskEventDraft(event_type="task.completed"))
            return self.store.get(task_id)

        service = CoreService(self.store, self.policy, {}, agent_runner=run_agent)

        first = await service.submit(self.agent_command())
        second = await service.submit(self.agent_command())

        self.assertEqual(first.status, TaskStatus.completed)
        self.assertEqual(second.status, TaskStatus.completed)
        self.assertEqual(calls, ["agent-task"])

    async def test_missing_agent_runner_fails_only_agent_task(self):
        adapter = RecordingAdapter()
        service = CoreService(self.store, self.policy, {"project.read": adapter})

        agent = await service.submit(self.agent_command())
        direct = await service.submit(self.command(task_id="direct-task", command_id="direct-command"))

        self.assertEqual(agent.status, TaskStatus.failed)
        self.assertEqual(agent.events[-1].payload.get("reason"), "agent runtime unavailable")
        self.assertEqual(direct.status, TaskStatus.completed)

    async def test_running_agent_task_resumes_once_after_service_restart(self):
        command = self.agent_command()
        self.store.create(command)
        self.store.append(command.task_id, TaskEventDraft(event_type="task.started"))
        calls = []

        async def resume_agent(task_id):
            calls.append(task_id)
            self.store.append(task_id, TaskEventDraft(event_type="task.completed"))
            return self.store.get(task_id)

        restarted = CoreService(self.store, self.policy, {}, agent_runner=resume_agent)

        result = await restarted.submit(command)

        self.assertEqual(result.status, TaskStatus.completed)
        self.assertEqual(calls, [command.task_id])

    async def test_permission_required_task_runs_after_explicit_approval(self):
        adapter = RecordingAdapter()
        service = CoreService(self.store, self.policy, {"project.read": adapter})
        payload = dict(self.command().payload)
        payload["operation"] = "install"
        command = self.command().model_copy(update={"payload": payload})

        pending = await service.submit(command)
        completed = await service.approve(command.task_id)

        self.assertEqual(pending.events[-1].event_type, "task.permission_required")
        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(len(adapter.calls), 1)

    async def test_submit_executes_once_per_idempotency_key_and_redacts_credentials(self):
        adapter = RecordingAdapter()
        service = CoreService(self.store, self.policy, {"project.read": adapter})

        first = await service.submit(self.command())
        second = await service.submit(self.command())

        self.assertEqual(first.status, TaskStatus.completed)
        self.assertEqual(second.status, TaskStatus.completed)
        self.assertEqual(len(adapter.calls), 1)
        persisted = " ".join(event.model_dump_json() for event in self.store.events("task-1"))
        self.assertNotIn("credential:github", persisted)

    async def test_adapter_failure_is_a_truthful_failed_attempt(self):
        service = CoreService(self.store, self.policy, {"project.read": RecordingAdapter(fail=True)})

        record = await service.submit(self.command())

        self.assertEqual(record.status, TaskStatus.failed)
        self.assertEqual(record.events[-1].event_type, "task.failed")
        self.assertNotIn("private adapter failure", record.events[-1].model_dump_json())

    async def test_restore_calls_the_configured_checkpoint_store(self):
        restored = []
        service = CoreService(
            self.store,
            self.policy,
            {"project.read": RecordingAdapter()},
            restore_checkpoint=restored.append,
        )

        service.restore("checkpoint-1")

        self.assertEqual(restored, ["checkpoint-1"])

    async def test_start_returns_before_adapter_completion_and_persists_live_events(self):
        adapter = BlockingAdapter()
        service = CoreService(self.store, self.policy, {"project.read": adapter})

        started = await service.start(self.command())
        await adapter.first_consumed.wait()

        self.assertEqual(started.status, TaskStatus.running)
        self.assertEqual(
            [event.payload.get("text") for event in service.subscribe("task-1") if event.event_type == "adapter.delta"],
            ["first"],
        )

        adapter.release.set()
        completed = await service.wait("task-1")

        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(
            [event.payload.get("text") for event in completed.events if event.event_type == "adapter.delta"],
            ["first", "second"],
        )

    async def test_wait_for_events_returns_only_sequences_after_the_cursor(self):
        adapter = BlockingAdapter()
        service = CoreService(self.store, self.policy, {"project.read": adapter})
        started = await service.start(self.command())
        await adapter.first_consumed.wait()
        cursor = next(event.sequence for event in service.subscribe("task-1") if event.event_type == "adapter.delta")

        waiting = asyncio.create_task(service.wait_for_events("task-1", cursor))
        adapter.release.set()
        events = await waiting
        await service.wait("task-1")

        self.assertTrue(events)
        self.assertTrue(all(event.sequence > cursor for event in events))
        self.assertEqual(len({event.sequence for event in events}), len(events))


if __name__ == "__main__":
    unittest.main()
