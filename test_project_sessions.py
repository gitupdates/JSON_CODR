import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from web_app.attachments import AttachmentService
from web_app.core.project_registry import ProjectRegistry
from web_app.models import ChatMessage, ObjectReference, ProjectSessionSaveRequest, ReasoningEntry, ReasoningTrace
from web_app.project_sessions import ProjectSessionService
from web_app.workspace import WorkspaceService


class ProjectSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.project_root = self.root / "registered-project"
        self.project_root.mkdir()
        self.registry = ProjectRegistry(self.root / "projects.sqlite")
        self.project = self.registry.register(self.project_root)
        self.workspace = WorkspaceService(self.root / "data")
        self.attachments = AttachmentService(self.workspace)
        self.sessions = ProjectSessionService(self.workspace, self.registry)

    def tearDown(self):
        self.registry.close()
        self.temporary_directory.cleanup()

    def _live_session(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        self.workspace.append_message(session.id, ChatMessage(
            role="user", content="Implement parser.py and verify the model output.",
            references=[ObjectReference(id="ref-1", kind="project_file", label="parser.py", target="parser.py")],
        ))
        self.workspace.append_message(session.id, ChatMessage(
            role="assistant", content="Parser implementation completed.", effective_model="local:model",
            reasoning=ReasoningTrace(entries=[ReasoningEntry(
                sequence=0, kind="analysis", text="private chain must never be summarized", provenance="native_provider",
            )]),
        ))
        self.attachments.import_stream(session.id, "notes.txt", io.BytesIO(b"attachment text"))
        artifacts = self.workspace.sessions_root / session.id / "artifacts"
        artifacts.mkdir()
        (artifacts / "result.md").write_text("artifact", encoding="utf-8")
        return session

    def test_save_creates_immutable_project_scoped_copy_with_bounded_safe_summary(self):
        session = self._live_session()

        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", ["Urgent", "parser"])
        snapshot_dir = self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
        manifest = self.workspace.get_session(session.id)

        self.assertEqual(snapshot.project_id, self.project.project_id)
        self.assertEqual(snapshot.owner_user_id, "owner-1")
        self.assertEqual(snapshot.source_session_id, session.id)
        self.assertTrue((snapshot_dir / "manifest.json").is_file())
        self.assertTrue((snapshot_dir / "originals").is_dir())
        self.assertTrue((snapshot_dir / "extracted").is_dir())
        self.assertTrue((snapshot_dir / "artifacts" / "result.md").is_file())
        self.assertIn("parser.py", snapshot.summary)
        self.assertNotIn("private chain", snapshot.summary)
        self.assertLessEqual(len(snapshot.summary), 8_000)
        self.assertIn("snapshot:" + snapshot.id, snapshot.keywords)
        self.assertIn("project:" + self.project.project_id, snapshot.keywords)
        self.assertIn("file:parser.py", snapshot.keywords)
        self.assertEqual(manifest.messages[0].content, "Implement parser.py and verify the model output.")

    def test_repeated_saves_are_distinct_and_restore_creates_owner_bound_new_session(self):
        session = self._live_session()
        first = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        second = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        restored = self.sessions.restore(first.id, self.project.project_id, "owner-1")
        live = self.workspace.get_session(restored.session_id)

        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(restored.session_id, session.id)
        self.assertEqual(live.owner_user_id, "owner-1")
        self.assertEqual(live.project_id, self.project.project_id)
        self.assertEqual([m.content for m in live.messages], [m.content for m in self.workspace.get_session(session.id).messages])
        self.assertEqual(len(live.attachments), 1)
        self.assertEqual((self.workspace.sessions_root / restored.session_id / "artifacts" / "result.md").read_text(encoding="utf-8"), "artifact")

    def test_owner_and_project_boundaries_deny_snapshot_access(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        other_root = self.root / "other-project"
        other_root.mkdir()
        other = self.registry.register(other_root)

        with self.assertRaises(KeyError):
            self.sessions.get(snapshot.id, self.project.project_id, "owner-2")
        with self.assertRaises(KeyError):
            self.sessions.restore(snapshot.id, other.project_id, "owner-1")
        with self.assertRaises(PermissionError):
            self.sessions.save(session.id, self.project.project_id, "owner-2", "Parser fix", "fix", [])

    def test_unsafe_or_partial_allowed_source_rejects_save_and_cleans_staging(self):
        session = self._live_session()
        attachment = self.workspace.get_session(session.id).attachments[0]
        (self.workspace.sessions_root / session.id / "originals" / attachment.storage_name).unlink()

        with self.assertRaises(ValueError):
            self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        staging = self.sessions.project_directory(self.project.project_id) / ".staging"
        self.assertFalse(staging.exists() and any(staging.iterdir()))

    def test_restore_rolls_back_new_live_session_when_snapshot_copy_fails(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        source = self.sessions.snapshot_directory(snapshot.id, self.project.project_id) / "originals"
        for path in source.iterdir():
            path.unlink()

        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        with self.assertRaises(ValueError):
            self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)

    def test_save_rejects_missing_or_traversal_attachment_storage_names(self):
        session = self._live_session()
        manifest = self.workspace.get_session(session.id)
        manifest.attachments[0].storage_name = "../../outside"
        self.workspace.save_manifest(manifest)

        with self.assertRaises(ValueError):
            self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        manifest.attachments[0].storage_name = None
        self.workspace.save_manifest(manifest)
        with self.assertRaises(ValueError):
            self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

    def test_snapshot_manifest_and_restore_exclude_private_reasoning_and_inflight_state(self):
        session = self._live_session()
        self.workspace.append_message(session.id, ChatMessage(role="assistant", content="still running", status="streaming", task_id="live-task"))

        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        stored = json.loads((self.sessions.snapshot_directory(snapshot.id, self.project.project_id) / "manifest.json").read_text(encoding="utf-8"))
        restored = self.workspace.get_session(self.sessions.restore(snapshot.id, self.project.project_id, "owner-1").session_id)

        self.assertEqual(len(stored["messages"]), 2)
        self.assertIsNone(stored["messages"][1]["reasoning"])
        self.assertTrue(all(message["status"] not in {"pending", "streaming"} and message["task_id"] is None for message in stored["messages"]))
        self.assertTrue(all(message.status not in {"pending", "streaming"} and message.task_id is None for message in restored.messages))

    def test_scoped_snapshot_misses_have_one_not_found_result(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        other_root = self.root / "different"
        other_root.mkdir()
        other = self.registry.register(other_root)

        for project_id, owner, snapshot_id in (
            (self.project.project_id, "owner-1", "f" * 32),
            (self.project.project_id, "owner-2", snapshot.id),
            (other.project_id, "owner-1", snapshot.id),
        ):
            with self.subTest(project_id=project_id, owner=owner), self.assertRaises(KeyError):
                self.sessions.get(snapshot_id, project_id, owner)

    def test_summary_keeps_required_categories_and_exact_identifiers_after_long_objective(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        self.workspace.append_message(session.id, ChatMessage(role="user", content="x" * 20_000))
        self.workspace.append_message(session.id, ChatMessage(role="assistant", content="done", status="completed", effective_model="model-x", task_id="task-x", references=[ObjectReference(id="r-x", kind="project_file", label="src/widget.py", target="src/widget.py")]))
        self.attachments.import_text(session.id, "note", "component:Widget")
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "My Title", "feature", ["component:Widget", "User Keyword"])

        self.assertLessEqual(len(snapshot.summary), 8_000)
        for text in ("Outcome (completed): done", "Model: model-x", "Task: task-x", "Reference: src/widget.py", "Attachment: component:Widget"):
            self.assertIn(text, snapshot.summary)
        for value in (f"session:{session.id}", "change-type:feature", "title:my-title", "file:src/widget.py", "component:widget", "model:model-x", "task:task-x", "reference:r-x", "user-keyword"):
            self.assertIn(value, snapshot.keywords)

    def test_save_sweeps_abandoned_same_parent_staging(self):
        session = self._live_session()
        sessions_root = self.sessions.project_directory(self.project.project_id) / "sessions"
        sessions_root.mkdir(parents=True)
        abandoned = sessions_root / (".staging-" + "a" * 32)
        abandoned.mkdir()
        (abandoned / "partial").write_text("partial", encoding="utf-8")

        self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        self.assertFalse(abandoned.exists())

    def test_save_request_validates_and_serializes_session_id(self):
        request = ProjectSessionSaveRequest(session_id="a" * 32, title="Title", change_type="fix")
        self.assertEqual(request.model_dump()["session_id"], "a" * 32)
        with self.assertRaises(ValueError):
            ProjectSessionSaveRequest(session_id="bad", title="Title", change_type="fix")

    def test_rejected_over_limit_and_session_limit_attachments_save_and_restore_as_metadata(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        limited = AttachmentService(self.workspace, max_file_bytes=2, max_session_bytes=3)
        with self.assertRaises(Exception):
            limited.import_text(session.id, "toolong", "large.txt")
        other = self.workspace.create_session("owner-1", self.project.project_id)
        session_limited = AttachmentService(self.workspace, max_file_bytes=3, max_session_bytes=3)
        session_limited.import_text(other.id, "abc", "one.txt")
        with self.assertRaises(Exception):
            session_limited.import_text(other.id, "de", "two.txt")

        for current in (session, other):
            snapshot = self.sessions.save(current.id, self.project.project_id, "owner-1", "Limits", "fix", [])
            restored = self.workspace.get_session(self.sessions.restore(snapshot.id, self.project.project_id, "owner-1").session_id)
            rejected = next(item for item in restored.attachments if item.extraction_state.value == "rejected")
            self.assertIsNone(rejected.digest)


if __name__ == "__main__":
    unittest.main()
