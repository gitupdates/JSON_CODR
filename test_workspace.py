import os
import tempfile
import unittest
from pathlib import Path

from web_app.models import ChatMessage
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

        self.assertEqual(restored.schema_version, 1)
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


if __name__ == "__main__":
    unittest.main()
