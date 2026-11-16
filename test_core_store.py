import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore, RetentionPolicy
from web_app.core.contracts import TaskCommand, TaskEvent, TaskEventDraft, TaskStatus
from web_app.core.store import ConcurrencyConflict, TaskStore


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
