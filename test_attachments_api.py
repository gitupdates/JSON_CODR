import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.attachments import AttachmentService, AttachmentTooLarge
from web_app.app import create_app
from web_app.workspace import WorkspaceService


class FakeOllamaService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []


class AttachmentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceService(Path(self.temporary_directory.name))
        self.session = self.workspace.create_session()
        self.service = AttachmentService(self.workspace)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_import_sanitizes_name_and_deduplicates_content(self):
        first = self.service.import_stream(self.session.id, "../secret.txt", io.BytesIO(b"hello"))
        second = self.service.import_stream(self.session.id, "copy.txt", io.BytesIO(b"hello"))
        self.assertEqual(first.display_name, "secret.txt")
        self.assertEqual(first.digest, second.digest)
        originals = list((Path(self.temporary_directory.name) / "sessions" / self.session.id / "originals").iterdir())
        self.assertEqual(len(originals), 1)

    def test_import_rejects_file_over_limit_but_keeps_review_record(self):
        service = AttachmentService(self.workspace, max_file_bytes=4)
        with self.assertRaises(AttachmentTooLarge):
            service.import_stream(self.session.id, "large.txt", io.BytesIO(b"12345"))
        record = self.workspace.get_session(self.session.id)
        self.assertEqual(record.attachments[0].extraction_state.value, "rejected")

    def test_import_enforces_file_count_and_session_byte_limits(self):
        count_limited = AttachmentService(self.workspace, max_files=1)
        count_limited.import_text(self.session.id, "one", "one.txt")
        with self.assertRaises(AttachmentTooLarge):
            count_limited.import_text(self.session.id, "two", "two.txt")

        other = self.workspace.create_session()
        byte_limited = AttachmentService(self.workspace, max_session_bytes=5)
        byte_limited.import_text(other.id, "123", "one.txt")
        with self.assertRaises(AttachmentTooLarge):
            byte_limited.import_text(other.id, "456", "two.txt")

    def test_include_preview_and_remove_lifecycle(self):
        attachment = self.service.import_text(self.session.id, "pasted content")
        self.service.set_included(self.session.id, attachment.id, False)
        self.assertFalse(self.workspace.get_session(self.session.id).attachments[0].included)
        self.assertEqual(self.service.preview(self.session.id, attachment.id)["text"], "pasted content")
        self.service.remove(self.session.id, attachment.id)
        self.assertEqual(self.workspace.get_session(self.session.id).attachments, [])

    def test_http_upload_paste_preview_include_and_delete(self):
        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.service))
        upload = client.post(
            f"/api/sessions/{self.session.id}/attachments",
            files={"file": ("notes.txt", b"file context", "text/plain")},
        )
        self.assertEqual(upload.status_code, 201)
        attachment_id = upload.json()["id"]
        pasted = client.post(
            f"/api/sessions/{self.session.id}/clipboard-text",
            json={"text": "clipboard context"},
        )
        self.assertEqual(pasted.status_code, 201)
        self.assertEqual(len(client.get(f"/api/sessions/{self.session.id}/attachments").json()), 2)
        self.assertEqual(
            client.get(f"/api/sessions/{self.session.id}/attachments/{attachment_id}/preview").json()["text"],
            "file context",
        )
        changed = client.patch(
            f"/api/sessions/{self.session.id}/attachments/{attachment_id}",
            json={"included": False},
        )
        self.assertFalse(changed.json()["included"])
        self.assertEqual(
            client.delete(f"/api/sessions/{self.session.id}/attachments/{attachment_id}").status_code,
            204,
        )

    def test_http_original_download_and_extraction_retry(self):
        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.service))
        upload = client.post(
            f"/api/sessions/{self.session.id}/attachments",
            files={"file": ("review.txt", b"review me", "text/plain")},
        )
        attachment_id = upload.json()["id"]

        original = client.get(
            f"/api/sessions/{self.session.id}/attachments/{attachment_id}/original"
        )
        self.assertEqual(original.status_code, 200)
        self.assertEqual(original.content, b"review me")
        self.assertIn("attachment", original.headers["content-disposition"])
        self.assertEqual(original.headers["x-content-type-options"], "nosniff")

        retried = client.post(
            f"/api/sessions/{self.session.id}/attachments/{attachment_id}/retry"
        )
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["extraction_state"], "ready")

    def test_http_exports_original_attachments_as_zip(self):
        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.service))
        self.service.import_text(self.session.id, "first", "notes.txt")
        self.service.import_text(self.session.id, "second", "notes.txt")

        response = client.get(f"/api/sessions/{self.session.id}/archive.zip")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["notes-2.txt", "notes.txt"])
            self.assertEqual(archive.read("notes.txt"), b"first")


if __name__ == "__main__":
    unittest.main()
