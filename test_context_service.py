import tempfile
import unittest
from pathlib import Path

from web_app.core.context_service import ContextOverflow, ContextService
from web_app.core.contracts import TaskCommand, TaskEventDraft
from web_app.core.memory import MemoryStore
from web_app.core.store import TaskStore


class ContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.tasks = TaskStore(root / "tasks.sqlite")
        self.memory = MemoryStore(root / "memory.sqlite")
        self.tasks.create(TaskCommand(
            command_id="parent-command", task_id="parent", thread_id="thread-1",
            project_id="project-1", command_type="agent.run",
        ))
        self.tasks.create(TaskCommand(
            command_id="child-command", task_id="child", thread_id="thread-1",
            project_id="project-1", parent_task_id="parent", command_type="project.read",
        ))
        self.context = ContextService(self.tasks, self.memory)

    def tearDown(self):
        self.memory.close()
        self.tasks.close()
        self.temporary.cleanup()

    def test_interleaved_events_follow_store_global_order(self):
        self.tasks.append("parent", TaskEventDraft(event_type="task.steered", payload={"input": "first"}))
        self.tasks.append("child", TaskEventDraft(event_type="capability.result", payload={"value": "second"}))

        bundle = self.context.assemble("thread-1", "parent", 10_000)

        first_position = bundle.text.index("first")
        second_position = bundle.text.index("second")
        self.assertLess(first_position, second_position)

    def test_compaction_is_durable_cursor_and_does_not_duplicate_old_sources(self):
        old = self.tasks.append("parent", TaskEventDraft(event_type="task.steered", payload={"input": "old"}))
        record = self.context.compact("thread-1")
        new = self.tasks.append("parent", TaskEventDraft(event_type="task.steered", payload={"input": "new"}))

        reopened = ContextService(self.tasks, self.memory)
        bundle = reopened.assemble("thread-1", "parent", 10_000)

        self.assertEqual(record.through_global_sequence, old.global_sequence)
        self.assertIn(f"event:{old.event_id}", record.source_refs)
        self.assertIn(f"event:{new.event_id}", [source.source_ref for source in bundle.sources])
        self.assertNotIn(f"event:{old.event_id}", [source.source_ref for source in bundle.sources])
        self.assertEqual(sum(source.kind == "context_compaction" for source in bundle.sources), 1)

    def test_mandatory_context_overflow_is_visible(self):
        self.tasks.append(
            "parent",
            TaskEventDraft(event_type="task.steered", payload={"input": "required direction"}),
        )

        with self.assertRaises(ContextOverflow):
            self.context.assemble("thread-1", "parent", 10)


if __name__ == "__main__":
    unittest.main()
