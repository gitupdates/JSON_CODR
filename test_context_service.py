import tempfile
import unittest
from pathlib import Path

from web_app.core.context_service import ContextOverflow, ContextService
from web_app.core.contracts import TaskCommand, TaskEventDraft
from web_app.core.memory import MemoryStore
from web_app.core.project_intelligence import ProjectReader
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
        self.assertEqual(
            [source.source_ref for source in bundle.sources].count(f"event:{old.event_id}"), 1
        )
        self.assertEqual(sum(source.kind == "context_compaction" for source in bundle.sources), 1)

    def test_mandatory_context_overflow_is_visible(self):
        self.tasks.append(
            "parent",
            TaskEventDraft(event_type="task.steered", payload={"input": "required direction"}),
        )

        with self.assertRaises(ContextOverflow):
            self.context.assemble("thread-1", "parent", 10)

    def test_project_snapshot_is_durable_mandatory_and_deduplicated(self):
        project = Path(self.temporary.name) / "project"
        project.mkdir()
        (project / "AGENTS.md").write_text("Always run the focused tests.", encoding="utf-8")
        (project / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        event = self.tasks.append(
            "parent",
            TaskEventDraft(event_type="task.steered", payload={"input": "inspect the project"}),
        )
        reader = ProjectReader(project)

        first = self.context.capture_project("thread-1", "parent", reader, target_path="app.py")
        second = self.context.capture_project("thread-1", "parent", reader, target_path="app.py")
        reopened = ContextService(self.tasks, self.memory)
        bundle = reopened.assemble("thread-1", "parent", 20_000)

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.through_global_sequence, event.global_sequence)
        self.assertEqual(
            len([record for record in self.memory.list("thread-1") if record.kind == "project_context_snapshot"]),
            1,
        )
        instruction = next(source for source in bundle.sources if source.kind == "project_instruction")
        project_file = next(
            source for source in bundle.sources
            if source.kind == "project_file" and source.source_ref.endswith(":file:app.py")
        )
        self.assertTrue(instruction.mandatory)
        self.assertEqual(instruction.trust, "untrusted_project")
        self.assertEqual(project_file.trust, "untrusted_project")
        self.assertIn("focused tests", instruction.content)
        self.assertIn("return 42", project_file.content)

    def test_snapshot_reports_omissions_without_exposing_secret_content(self):
        project = Path(self.temporary.name) / "secret-project"
        project.mkdir()
        (project / ".env").write_text("PASSWORD=never-leak", encoding="utf-8")
        (project / "app.py").write_text("value = 1", encoding="utf-8")
        self.context.capture_project("thread-1", "parent", ProjectReader(project))

        bundle = self.context.assemble("thread-1", "parent", 20_000)

        omission = next(source for source in bundle.sources if source.kind == "project_omission")
        self.assertEqual(omission.trust, "trusted_runtime_metadata")
        self.assertIn("sensitive_path", omission.content)
        self.assertNotIn("never-leak", bundle.text)

    def test_compaction_retains_large_mandatory_project_instructions_after_reopen(self):
        project = Path(self.temporary.name) / "large-project"
        project.mkdir()
        instruction = "MANDATORY-INSTRUCTION\n" + ("x" * 9_000)
        (project / "AGENTS.md").write_text(instruction, encoding="utf-8")
        self.context.capture_project("thread-1", "parent", ProjectReader(project))

        self.context.compact("thread-1")
        bundle = ContextService(self.tasks, self.memory).assemble("thread-1", "parent", 20_000)

        matching = [source for source in bundle.sources if "MANDATORY-INSTRUCTION" in source.content]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0].mandatory)

    def test_new_project_snapshot_replaces_previous_snapshot_for_thread(self):
        project = Path(self.temporary.name) / "changing-project"
        project.mkdir()
        path = project / "app.py"
        path.write_text("value = 1\n", encoding="utf-8")
        first = self.context.capture_project("thread-1", "parent", ProjectReader(project))
        path.write_text("value = 2\n", encoding="utf-8")

        second = self.context.capture_project("thread-1", "parent", ProjectReader(project))

        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        snapshots = [record for record in self.memory.list("thread-1") if record.kind == "project_context_snapshot"]
        self.assertEqual(len(snapshots), 1)


if __name__ == "__main__":
    unittest.main()
