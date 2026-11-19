import json
import os
import tempfile
import unittest
from pathlib import Path

from web_app.models import ChatMessage, MessageArtifact, ObjectReference, ReasoningEntry, ReasoningTrace
from web_app.workspace import InvalidSessionId, WorkspaceService


class WorkspaceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_session_round_trips_across_service_instances(self):
        first = WorkspaceService(self.data_root)
        session = first.create_session()
        first.append_message(session.id, ChatMessage(role="user", content="hello"))

        restored = WorkspaceService(self.data_root).get_session(session.id)

        self.assertEqual(restored.schema_version, 2)
        self.assertEqual(restored.messages[0].content, "hello")
        self.assertRegex(restored.id, r"^[0-9a-f]{32}$")

    def test_delete_session_removes_its_workspace(self):
        service = WorkspaceService(self.data_root)
        session = service.create_session()

        service.delete_session(session.id)

        with self.assertRaises(KeyError):
            service.get_session(session.id)
        self.assertFalse((self.data_root / "sessions" / session.id).exists())

    def test_malicious_session_ids_are_rejected(self):
        service = WorkspaceService(self.data_root)
        for value in ("../outside", "..\\outside", "C:\\outside", "", "not-an-id"):
            with self.subTest(value=value), self.assertRaises(InvalidSessionId):
                service.get_session(value)

    def test_reparse_point_session_directory_is_rejected(self):
        service = WorkspaceService(self.data_root)
        session_id = "a" * 32
        outside = self.data_root / "outside"
        outside.mkdir()
        link = self.data_root / "sessions" / session_id
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Directory symlinks unavailable: {error}")

        with self.assertRaises(InvalidSessionId):
            service.get_session(session_id)

    def test_incomplete_temporary_manifest_is_ignored(self):
        service = WorkspaceService(self.data_root)
        session = service.create_session()
        session_directory = self.data_root / "sessions" / session.id
        (session_directory / "manifest.json.tmp").write_text("{", encoding="utf-8")

        restored = WorkspaceService(self.data_root).get_session(session.id)

        self.assertEqual(restored.id, session.id)
        self.assertEqual(restored.messages, [])

    def test_legacy_session_migrates_skill_routing_defaults_and_deduplicates_exclusions(self):
        service = WorkspaceService(self.data_root)
        record = service.create_session()
        manifest = service.sessions_root / record.id / "manifest.json"
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        raw["schema_version"] = 1
        raw.pop("auto_attach_skills", None)
        raw["excluded_skill_ids"] = ["pack:skill", "pack:skill"]
        manifest.write_text(json.dumps(raw), encoding="utf-8")

        migrated = service.get_session(record.id)

        self.assertEqual(migrated.schema_version, 2)
        self.assertTrue(migrated.auto_attach_skills)
        self.assertEqual(migrated.excluded_skill_ids, ["pack:skill"])

    def test_auditable_message_round_trips_with_stable_identity_and_typed_details(self):
        service = WorkspaceService(self.data_root)
        session = service.create_session()
        message = ChatMessage(
            role="assistant",
            content="Reviewed the file.",
            status="completed",
            task_id="task-123",
            requested_model="requested:model",
            effective_model="effective:model",
            reasoning=ReasoningTrace(entries=[ReasoningEntry(
                sequence=0,
                kind="evidence",
                text="The manifest contains the expected key.",
                provenance="native_provider",
                reference_ids=["attachment-1"],
            )]),
            references=[ObjectReference(
                id="attachment-1",
                kind="attachment",
                label="manifest.json",
                target="attachment-1",
                download_url="/api/sessions/session/attachments/attachment-1/original",
            )],
            attachment_ids=["attachment-1"],
            artifacts=[MessageArtifact(
                id="artifact-1",
                filename="review.md",
                media_type="text/markdown",
                size=42,
                download_url="/api/tasks/task-123/artifacts/artifact-1",
            )],
        )

        service.append_message(session.id, message)
        first = WorkspaceService(self.data_root).get_session(session.id).messages[0]
        second = WorkspaceService(self.data_root).get_session(session.id).messages[0]

        self.assertEqual(first.id, message.id)
        self.assertEqual(second.id, first.id)
        self.assertEqual(first.reasoning.entries[0].provenance, "native_provider")
        self.assertEqual(first.references[0].kind, "attachment")
        self.assertEqual(first.artifacts[0].filename, "review.md")

    def test_legacy_message_is_migrated_once_with_a_stable_id_and_defaults(self):
        service = WorkspaceService(self.data_root)
        session = service.create_session()
        manifest = service.sessions_root / session.id / "manifest.json"
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        raw["messages"] = [{"role": "assistant", "content": "legacy"}]
        manifest.write_text(json.dumps(raw), encoding="utf-8")

        first = service.get_session(session.id).messages[0]
        second = service.get_session(session.id).messages[0]

        self.assertRegex(first.id, r"^[0-9a-f]{32}$")
        self.assertEqual(second.id, first.id)
        self.assertEqual(first.status, "completed")
        self.assertEqual(first.references, [])
        self.assertIsNone(first.reasoning)

    def test_reasoning_contract_rejects_unknown_provenance(self):
        with self.assertRaises(ValueError):
            ReasoningEntry(
                sequence=0,
                kind="analysis",
                text="unsupported",
                provenance="invented",
            )


if __name__ == "__main__":
    unittest.main()
