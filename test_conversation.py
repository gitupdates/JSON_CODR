import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.attachments import AttachmentService
from web_app.app import create_app
from web_app.conversation import ConversationService
from web_app.models import ChatMessage, ObjectReference
from web_app.workspace import WorkspaceService


class ConversationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.project = root / "project"
        self.project.mkdir()
        self.workspace = WorkspaceService(root / "data")
        self.attachments = AttachmentService(self.workspace)
        self.service = ConversationService(self.workspace, self.attachments, self.project)
        self.session = self.workspace.create_session()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_history_preserves_order_and_task_linkage(self):
        first = ChatMessage(role="user", content="Inspect this")
        second = ChatMessage(
            role="assistant",
            content="Inspection complete",
            task_id="task-42",
            requested_model="requested",
            effective_model="effective",
            parent_message_id=first.id,
        )
        self.workspace.append_message(self.session.id, first)
        self.workspace.append_message(self.session.id, second)

        history = self.service.history(self.session.id)

        self.assertEqual([item.id for item in history], [first.id, second.id])
        self.assertEqual(history[1].task_id, "task-42")
        self.assertEqual(history[1].parent_message_id, first.id)

    def test_exports_message_and_session_as_markdown_and_json(self):
        message = ChatMessage(role="assistant", content="Result **with evidence**", task_id="task-7")
        self.workspace.append_message(self.session.id, message)

        markdown, markdown_type, markdown_name = self.service.export_message(
            self.session.id, message.id, "markdown"
        )
        payload, json_type, json_name = self.service.export_session(self.session.id, "json")

        self.assertIn("Result **with evidence**", markdown.decode())
        self.assertEqual(markdown_type, "text/markdown")
        self.assertTrue(markdown_name.endswith(".md"))
        self.assertEqual(json.loads(payload)["messages"][0]["task_id"], "task-7")
        self.assertEqual(json_type, "application/json")
        self.assertTrue(json_name.endswith(".json"))

    def test_binary_zip_inclusion_is_explicit_opt_in(self):
        attachment = self.attachments.import_stream(
            self.session.id, "evidence.txt", io.BytesIO(b"private evidence")
        )

        without_binaries, _, _ = self.service.export_session(self.session.id, "zip")
        with_binaries, _, _ = self.service.export_session(
            self.session.id, "zip", include_binaries=True
        )

        with zipfile.ZipFile(io.BytesIO(without_binaries)) as archive:
            self.assertEqual(archive.namelist(), ["conversation.json", "conversation.md"])
        with zipfile.ZipFile(io.BytesIO(with_binaries)) as archive:
            self.assertIn(f"attachments/{attachment.display_name}", archive.namelist())

    def test_reference_resolution_is_scoped_to_session_and_project(self):
        attachment = self.attachments.import_stream(
            self.session.id, "evidence.txt", io.BytesIO(b"evidence")
        )
        project_file = self.project / "src" / "main.py"
        project_file.parent.mkdir()
        project_file.write_text("print('ok')", encoding="utf-8")

        attachment_path, _ = self.service.resolve_reference(
            self.session.id,
            ObjectReference(
                id=attachment.id,
                kind="attachment",
                label="evidence",
                target=attachment.id,
            ),
        )
        project_path, _ = self.service.resolve_reference(
            self.session.id,
            ObjectReference(
                id="project-main",
                kind="project_file",
                label="main.py",
                target="src/main.py",
            ),
        )

        self.assertEqual(attachment_path.read_bytes(), b"evidence")
        self.assertEqual(project_path, project_file)
        with self.assertRaises(PermissionError):
            self.service.resolve_reference(
                self.session.id,
                ObjectReference(
                    id="escape",
                    kind="project_file",
                    label="escape",
                    target="../outside.txt",
                ),
            )

    def test_missing_and_cross_session_objects_are_rejected(self):
        other = self.workspace.create_session()
        foreign = self.attachments.import_stream(other.id, "foreign.txt", io.BytesIO(b"foreign"))
        reference = ObjectReference(
            id=foreign.id,
            kind="attachment",
            label="foreign",
            target=foreign.id,
        )

        with self.assertRaises(KeyError):
            self.service.resolve_reference(self.session.id, reference)

    def test_http_history_exports_and_reference_download(self):
        class FakeOllamaService:
            async def health(self):
                return {"ollama": True}

            async def list_models(self):
                return []

        attachment = self.attachments.import_stream(
            self.session.id, "evidence.txt", io.BytesIO(b"download me")
        )
        message = ChatMessage(
            role="assistant",
            content="Evidence attached",
            references=[ObjectReference(
                id="evidence-ref",
                kind="attachment",
                label="evidence.txt",
                target=attachment.id,
            )],
        )
        self.workspace.append_message(self.session.id, message)
        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.attachments))

        history = client.get(f"/api/sessions/{self.session.id}/conversation")
        exported = client.get(
            f"/api/sessions/{self.session.id}/conversation/export?format=markdown"
        )
        downloaded = client.get(
            f"/api/sessions/{self.session.id}/references/evidence-ref"
        )

        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["id"], message.id)
        self.assertEqual(exported.status_code, 200)
        self.assertIn("Evidence attached", exported.text)
        self.assertEqual(downloaded.content, b"download me")

        appended = client.post(
            f"/api/sessions/{self.session.id}/conversation",
            json={
                "role": "assistant",
                "content": "A streamed response",
                "status": "completed",
                "task_id": "task-streamed",
                "requested_model": "requested",
                "effective_model": "effective",
            },
        )
        self.assertEqual(appended.status_code, 201)
        self.assertEqual(appended.json()["task_id"], "task-streamed")

    def test_http_missing_reference_does_not_disclose_paths(self):
        class FakeOllamaService:
            async def health(self):
                return {"ollama": True}

            async def list_models(self):
                return []

        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.attachments))

        response = client.get(f"/api/sessions/{self.session.id}/references/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Reference not found"})


if __name__ == "__main__":
    unittest.main()
