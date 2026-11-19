import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore, RetentionPolicy
from web_app.core.contracts import (
    EffectIntent,
    EffectIntentDraft,
    EffectState,
    TaskCommand,
    TaskEvent,
    TaskEventDraft,
    TaskStatus,
)
from web_app.core.store import ConcurrencyConflict, IntegrityViolation, InvalidEffectTransition, TaskStore


def command(task_id: str, command_id: str | None = None, parent_task_id: str | None = None) -> TaskCommand:
    return TaskCommand(
        command_id=command_id or f"command-{task_id}",
        task_id=task_id,
        thread_id="thread-1",
        project_id="project-1",
        parent_task_id=parent_task_id,
        command_type="test.run",
        payload={"value": task_id},
    )


def effect(effect_id: str = "effect-1") -> EffectIntentDraft:
    return EffectIntentDraft(
        effect_id=effect_id,
        capability_id="inference.ollama",
        operation="chat",
        payload={"model": "qwen3:4b", "prompt": "hello"},
        principal="user",
        project_root="D:/JSON_CODR_alpha",
        effect_class="inference",
        approval_required=False,
        retry_classification="reconcile_before_retry",
        reconciler_id="ollama.chat",
        correlation_id="correlation-1",
        causation_id="command-task-1",
    )


class TaskStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "core.sqlite"
        self.store = TaskStore(self.database)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_create_is_atomic_and_idempotent(self):
        created = self.store.create(command("task-1", "same-command"))
        repeated = self.store.create(command("task-1", "same-command"))

        self.assertEqual(created, repeated)
        self.assertEqual(created.status, TaskStatus.pending)
        self.assertEqual([event.sequence for event in created.events], [0])
        self.assertEqual(created.events[0].event_type, "task.created")
        self.assertEqual(created.events[0].source, "json-codr://core/task-store")
        self.assertEqual(created.events[0].subject, "tasks/task-1")
        self.assertEqual(created.events[0].causation_id, "same-command")

    def test_durable_event_is_not_accepted_as_an_event_draft(self):
        self.assertFalse(issubclass(TaskEvent, TaskEventDraft))

    def test_idempotency_key_cannot_be_reused_for_another_task(self):
        self.store.create(command("task-1", "same-command"))

        with self.assertRaises(ConcurrencyConflict):
            self.store.create(command("task-2", "same-command"))

    def test_append_assigns_monotonic_sequences_under_concurrency(self):
        self.store.create(command("task-1"))
        barrier = threading.Barrier(9)
        failures: list[Exception] = []

        def append(index: int) -> None:
            try:
                barrier.wait()
                self.store.append(
                    "task-1",
                    TaskEventDraft(event_type="worker.progress", payload={"worker": index}),
                )
            except Exception as error:  # pragma: no cover - surfaced by assertion
                failures.append(error)

        threads = [threading.Thread(target=append, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        events = self.store.events("task-1")
        self.assertEqual([event.sequence for event in events], list(range(9)))
        self.assertEqual(len({event.event_id for event in events}), 9)
        self.assertTrue(all(event.event_id.version == 7 for event in events))
        self.assertEqual([event.sequence for event in self.store.events("task-1", after_sequence=5)], [6, 7, 8])

    def test_expected_version_prevents_stale_mutation(self):
        self.store.create(command("task-1"))
        self.store.append("task-1", TaskEventDraft(event_type="task.started"), expected_version=0)

        with self.assertRaises(ConcurrencyConflict):
            self.store.append("task-1", TaskEventDraft(event_type="worker.progress"), expected_version=0)

    def test_planned_step_and_child_are_reserved_atomically_and_replayed(self):
        self.store.create(command("parent"))
        child_command = command("child", command_id="step-command", parent_task_id="parent")

        first = self.store.plan_step_and_create_child(
            "parent", "plan-1", 1, "step-1", child_command, expected_version=0
        )
        replayed = self.store.plan_step_and_create_child(
            "parent", "plan-1", 1, "step-1", child_command
        )

        self.assertTrue(first.created)
        self.assertFalse(replayed.created)
        self.assertEqual(first.child, replayed.child)
        self.assertEqual(first.step_event, replayed.step_event)
        self.assertEqual([item.task_id for item in self.store.children("parent")], ["child"])
        self.assertEqual(
            [event.event_type for event in self.store.events("parent")],
            ["task.created", "agent.step_planned"],
        )

    def test_planned_step_rejects_a_different_child_on_replay(self):
        self.store.create(command("parent"))
        self.store.plan_step_and_create_child(
            "parent", "plan-1", 1, "step-1", command("child", parent_task_id="parent")
        )

        with self.assertRaises(ConcurrencyConflict):
            self.store.plan_step_and_create_child(
                "parent", "plan-1", 1, "step-1", command("other", parent_task_id="parent")
            )

    def test_thread_events_have_store_assigned_global_order(self):
        self.store.create(command("parent"))
        self.store.create(command("child", parent_task_id="parent"))
        self.store.append("parent", TaskEventDraft(event_type="parent.progress"))
        self.store.append("child", TaskEventDraft(event_type="child.progress"))

        ordered = self.store.thread_events("thread-1")

        self.assertEqual([item.global_sequence for item in ordered], list(range(4)))
        self.assertEqual([item.task_id for item in ordered], ["parent", "child", "parent", "child"])

    def test_event_hash_chain_detects_persisted_tampering(self):
        created = self.store.create(command("task-1"))
        appended = self.store.append("task-1", TaskEventDraft(event_type="task.started"))
        self.assertEqual(appended.previous_event_digest, created.events[0].event_digest)
        self.assertRegex(appended.event_digest, r"^sha256:[0-9a-f]{64}$")

        with self.store._connection:
            row = self.store._connection.execute(
                "SELECT event_json FROM task_events WHERE task_id = ? AND sequence = 1", ("task-1",)
            ).fetchone()
            event = json.loads(row["event_json"])
            event["payload"] = {"forged": True}
            self.store._connection.execute(
                "UPDATE task_events SET event_json = ? WHERE task_id = ? AND sequence = 1",
                (json.dumps(event), "task-1"),
            )

        with self.assertRaises(IntegrityViolation):
            self.store.events("task-1")

    def test_parent_child_links_and_cancel_request_are_durable(self):
        self.store.create(command("parent"))
        self.store.create(command("child", parent_task_id="parent"))

        cancelled = self.store.request_cancel("child")
        reopened = TaskStore(self.database)
        try:
            self.assertEqual([record.task_id for record in reopened.children("parent")], ["child"])
            self.assertEqual(cancelled.status, TaskStatus.cancel_requested)
            self.assertEqual(reopened.get("child").status, TaskStatus.cancel_requested)
        finally:
            reopened.close()

    def test_recovery_marks_unresolved_work_interrupted(self):
        self.store.create(command("running"))
        self.store.append("running", TaskEventDraft(event_type="task.started"))
        self.store.create(command("pending"))

        recovered = self.store.recover_interrupted()

        self.assertEqual([record.task_id for record in recovered], ["running"])
        self.assertEqual(self.store.get("running").status, TaskStatus.interrupted)
        self.assertEqual(self.store.get("pending").status, TaskStatus.pending)

    def test_effect_draft_does_not_accept_store_assigned_fields(self):
        self.assertFalse(issubclass(EffectIntent, EffectIntentDraft))
        with self.assertRaises(ValueError):
            EffectIntentDraft(**effect().model_dump(), state=EffectState.pending)

    def test_event_and_effect_are_reserved_atomically_and_replayed(self):
        self.store.create(command("task-1"))

        first = self.store.append_with_effect(
            "task-1", TaskEventDraft(event_type="effect.requested"), effect()
        )
        replayed = self.store.append_with_effect(
            "task-1", TaskEventDraft(event_type="effect.requested"), effect()
        )

        self.assertTrue(first.created)
        self.assertFalse(replayed.created)
        self.assertEqual(first.effect, replayed.effect)
        self.assertEqual(first.event, replayed.event)
        self.assertEqual(first.effect.state, EffectState.pending)
        self.assertEqual(len(self.store.effects("task-1")), 1)
        self.assertEqual(
            [event.event_type for event in self.store.events("task-1")],
            ["task.created", "effect.requested"],
        )

    def test_effect_replay_rejects_changed_intent(self):
        self.store.create(command("task-1"))
        self.store.append_with_effect("task-1", TaskEventDraft(event_type="effect.requested"), effect())
        changed = effect().model_copy(update={"operation": "generate"})

        with self.assertRaises(ConcurrencyConflict):
            self.store.append_with_effect("task-1", TaskEventDraft(event_type="effect.requested"), changed)

    def test_effect_reservation_rolls_back_if_event_append_fails(self):
        self.store.create(command("task-1"))

        with self.assertRaises(ConcurrencyConflict):
            self.store.append_with_effect(
                "task-1", TaskEventDraft(event_type="effect.requested"), effect(), expected_version=-1
            )

        self.assertEqual(self.store.effects("task-1"), ())
        self.assertEqual([event.event_type for event in self.store.events("task-1")], ["task.created"])

    def test_unknown_effect_blocks_completion_until_reconciled(self):
        self.store.create(command("task-1"))
        self.store.append_with_effect("task-1", TaskEventDraft(event_type="effect.requested"), effect())
        self.store.transition_effect("task-1", "effect-1", EffectState.leased, expected_state=EffectState.pending)
        self.store.transition_effect("task-1", "effect-1", EffectState.running, expected_state=EffectState.leased)
        self.store.transition_effect(
            "task-1", "effect-1", EffectState.unknown_requires_reconciliation,
            expected_state=EffectState.running,
        )

        with self.assertRaises(InvalidEffectTransition):
            self.store.append("task-1", TaskEventDraft(event_type="task.completed"))

        reconciled = self.store.reconcile_effect("task-1", "effect-1", "succeeded")
        self.assertEqual(reconciled.state, EffectState.succeeded)
        self.store.append("task-1", TaskEventDraft(event_type="task.completed"))
        self.assertEqual(self.store.get("task-1").status, TaskStatus.completed)

    def test_effect_state_and_attempts_survive_restart(self):
        self.store.create(command("task-1"))
        self.store.append_with_effect("task-1", TaskEventDraft(event_type="effect.requested"), effect())
        self.store.transition_effect(
            "task-1", "effect-1", EffectState.leased, expected_state=EffectState.pending,
            lease_owner="dispatcher-1",
        )

        reopened = TaskStore(self.database)
        try:
            restored = reopened.effect("task-1", "effect-1")
            self.assertEqual(restored.state, EffectState.leased)
            self.assertEqual(restored.attempt_count, 1)
            self.assertEqual(restored.lease_owner, "dispatcher-1")
        finally:
            reopened.close()


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_put_is_content_addressed_and_redacts_sensitive_metadata(self):
        first = self.store.put(
            io.BytesIO(b"same content"),
            ArtifactMetadata(
                task_id="task-1",
                media_type="text/plain",
                metadata={"token": "secret", "name": "result", "nested": {"authorization": "bearer secret"}},
            ),
        )
        second = self.store.put(
            io.BytesIO(b"same content"),
            ArtifactMetadata(task_id="task-1", media_type="text/plain", metadata={"name": "result"}),
        )

        self.assertEqual(first.artifact_id, second.artifact_id)
        self.assertEqual(first.digest, "sha256:a636bd7cd42060a4d07fa1bfbcc010eb7794c2ba721e1e3e4c20335a15b66eaf")
        with self.store.open(first.artifact_id) as stream:
            self.assertEqual(stream.read(), b"same content")
        manifest = self.store.export_manifest("task-1")
        encoded = json.dumps(manifest, sort_keys=True)
        self.assertNotIn("secret", encoded)
        self.assertNotIn("token", encoded)
        self.assertNotIn("authorization", encoded)
        self.assertIn("result", encoded)
        self.assertRegex(first.metadata_digest, r"^sha256:[0-9a-f]{64}$")

    def test_metadata_digest_uses_canonical_object_order(self):
        first = self.store.put(
            io.BytesIO(b"first"),
            ArtifactMetadata(media_type="application/json", metadata={"b": 2, "a": 1}),
        )
        second = self.store.put(
            io.BytesIO(b"second"),
            ArtifactMetadata(media_type="application/json", metadata={"a": 1, "b": 2}),
        )

        self.assertEqual(first.metadata_digest, second.metadata_digest)

    def test_prune_keeps_referenced_content_and_removes_unreferenced_content(self):
        kept = self.store.put(io.BytesIO(b"kept"), ArtifactMetadata(task_id="task-1", media_type="text/plain"))
        removed = self.store.put(io.BytesIO(b"removed"), ArtifactMetadata(media_type="text/plain"))

        pruned = self.store.prune(RetentionPolicy(max_unreferenced=0))

        self.assertEqual(pruned, (removed.artifact_id,))
        with self.store.open(kept.artifact_id) as stream:
            self.assertEqual(stream.read(), b"kept")
        with self.assertRaises(FileNotFoundError):
            self.store.open(removed.artifact_id)


if __name__ == "__main__":
    unittest.main()
