import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from web_app.core.contracts import EffectIntentDraft, EffectState, TaskCommand, TaskEventDraft
from web_app.core.effect_dispatcher import EffectDispatcher
from web_app.core.store import TaskStore


def command(task_id: str) -> TaskCommand:
    return TaskCommand(
        command_id=f"command-{task_id}",
        task_id=task_id,
        thread_id="thread-1",
        project_id="project-1",
        command_type="test.run",
    )


def effect(task_id: str) -> EffectIntentDraft:
    return EffectIntentDraft(
        effect_id=f"effect-{task_id}",
        capability_id="test.effect",
        operation="run",
        payload={"task": task_id},
        principal="user",
        project_root="D:/JSON_CODR_alpha",
        effect_class="test",
        approval_required=False,
        retry_classification="reconcile_before_retry",
        reconciler_id="test.reconciler",
        correlation_id=f"correlation-{task_id}",
        causation_id=f"command-{task_id}",
    )


class EffectDispatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "core.sqlite"
        self.store = TaskStore(self.database)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def reserve(self, task_id: str) -> None:
        self.store.create(command(task_id))
        self.store.append_with_effect(
            task_id,
            TaskEventDraft(event_type="effect.requested"),
            effect(task_id),
        )

    async def test_dispatcher_leases_only_the_configured_bound_and_completes_effects(self):
        for task_id in ("task-1", "task-2", "task-3"):
            self.reserve(task_id)
        calls: list[str] = []

        async def execute(intent):
            calls.append(intent.task_id)

        dispatcher = EffectDispatcher(
            self.store,
            {"test.effect": execute},
            owner="dispatcher-1",
            concurrency=2,
        )

        processed = await dispatcher.drain_once()

        self.assertEqual(processed, 2)
        self.assertEqual(calls, ["task-1", "task-2"])
        self.assertEqual(self.store.effect("task-1", "effect-task-1").state, EffectState.succeeded)
        self.assertEqual(self.store.effect("task-2", "effect-task-2").state, EffectState.succeeded)
        self.assertEqual(self.store.effect("task-3", "effect-task-3").state, EffectState.pending)

    async def test_execution_failure_becomes_unknown_and_is_not_automatically_released(self):
        self.reserve("task-1")

        async def execute(_intent):
            raise RuntimeError("connection lost after send")

        dispatcher = EffectDispatcher(
            self.store,
            {"test.effect": execute},
            owner="dispatcher-1",
            concurrency=1,
        )

        self.assertEqual(await dispatcher.drain_once(), 1)
        unknown = self.store.effect("task-1", "effect-task-1")
        self.assertEqual(unknown.state, EffectState.unknown_requires_reconciliation)
        self.assertEqual(await dispatcher.drain_once(), 0)

    async def test_expired_lease_recovers_to_unknown_after_restart(self):
        self.reserve("task-1")
        start = datetime(2026, 11, 17, tzinfo=UTC)
        leased = self.store.lease_pending_effects(
            owner="dispatcher-1",
            limit=1,
            lease_duration=timedelta(seconds=30),
            now=start,
        )
        self.assertEqual(leased[0].state, EffectState.leased)
        self.store.close()
        self.store = TaskStore(self.database)

        recovered = self.store.recover_expired_effect_leases(now=start + timedelta(seconds=31))

        self.assertEqual([item.effect_id for item in recovered], ["effect-task-1"])
        self.assertEqual(recovered[0].state, EffectState.unknown_requires_reconciliation)

    async def test_missing_handler_fails_before_external_execution(self):
        self.reserve("task-1")
        dispatcher = EffectDispatcher(self.store, {}, owner="dispatcher-1", concurrency=1)

        self.assertEqual(await dispatcher.drain_once(), 1)

        self.assertEqual(self.store.effect("task-1", "effect-task-1").state, EffectState.failed)


if __name__ == "__main__":
    unittest.main()
