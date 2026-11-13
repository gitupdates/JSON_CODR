import asyncio
import unittest
import tempfile
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.models import ChatResult, ConversionBundle, GeneratedFile
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaService, OllamaUnavailableError
from web_app.workspace import WorkspaceService


class FakeService:
    def __init__(self) -> None:
        self.available = True
        self.error = None
        self.last_prompt = None
        self.last_images = []
        self.vision = False

    async def health(self):
        return {"ollama": self.available}

    async def list_models(self):
        return [
            {
                "name": "qwen2.5-coder:7b-instruct-q4_K_M",
                "installed": True,
                "size": 4683087561,
                "quantization": "Q4_K_M",
                "context_length": 32768,
                "capabilities": ["completion", "tools", "insert"],
            },
            {
                "name": "opencoder:8b",
                "installed": False,
                "size": None,
                "quantization": None,
                "context_length": None,
                "capabilities": [],
            },
        ]

    async def supports_vision(self, model):
        return self.vision

    async def chat(self, model, prompt, images=None):
        self.last_prompt = prompt
        self.last_images = images or []
        if self.error:
            raise self.error
        if model in {"qwen", "qwen2.5-coder", "qwen2.5-coder:7b-instruct-q4_K_M"}:
            return ChatResult(
                model="qwen2.5-coder:7b-instruct-q4_K_M",
                status="ready",
                summary="Ready",
                content=f"Answered: {prompt}",
            )
        if model == "opencoder:8b":
            raise OllamaUnavailableError("Model is not installed")
        raise ValueError("Unknown or ambiguous model")

    async def convert_archive(self, model, prompt):
        self.last_prompt = prompt
        return ConversionBundle(
            summary="Converted Claude skills for local use.",
            files=[
                GeneratedFile(path="README-CONVERTED.md", content="# Converted usage"),
                GeneratedFile(path="skills/example/SKILL.md", content="# Example skill"),
            ],
        )


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceService(Path(self.temporary_directory.name))
        self.client = TestClient(create_app(self.service, self.workspace))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_sessions_create_reopen_and_delete(self):
        created = self.client.post("/api/sessions")
        self.assertEqual(created.status_code, 201)
        session_id = created.json()["id"]

        reopened = self.client.get(f"/api/sessions/{session_id}")
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.json()["schema_version"], 1)

        deleted = self.client.delete(f"/api/sessions/{session_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").status_code, 404)

    def test_session_path_traversal_is_rejected(self):
        response = self.client.get("/api/sessions/not-an-id")
        self.assertEqual(response.status_code, 400)

    def test_health_reports_ollama_readiness(self):
        self.assertEqual(
            self.client.get("/api/health").json(),
            {"status": "ready", "ollama": True},
        )
        self.service.available = False
        self.assertEqual(self.client.get("/api/health").json()["status"], "degraded")

    def test_models_keep_missing_configured_entries_disabled(self):
        response = self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["models"]), 2)
        self.assertFalse(response.json()["models"][1]["installed"])

    def test_low_memory_coder_is_selectable_when_installed(self):
        class LowMemoryClient:
            async def list(self):
                return {
                    "models": [{
                        "name": "qwen2.5-coder:0.5b",
                        "size": 398_000_000,
                        "details": {"quantization_level": "Q4_K_M"},
                    }]
                }

        models = asyncio.run(OllamaService(client=LowMemoryClient()).list_models())
        names = [model["name"] for model in models]

        self.assertIn("qwen2.5-coder:0.5b", names)
        low_memory = models[names.index("qwen2.5-coder:0.5b")]
        self.assertTrue(low_memory["installed"])
        self.assertEqual(low_memory["size"], 398_000_000)

    def test_chat_accepts_exact_and_unique_shorthand_models(self):
        for model in ("qwen", "qwen2.5-coder:7b-instruct-q4_K_M"):
            response = self.client.post("/api/chat", json={"model": model, "prompt": "Hello"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["model"], "qwen2.5-coder:7b-instruct-q4_K_M")
            self.assertEqual(response.json()["status"], "ready")
            self.assertIsNone(response.json()["error"])

    def test_empty_prompt_is_rejected(self):
        response = self.client.post("/api/chat", json={"model": "qwen", "prompt": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Prompt must not be empty")

    def test_session_chat_includes_selected_attachment_text_and_persists_messages(self):
        from web_app.attachments import AttachmentService

        session = self.workspace.create_session()
        attachment = AttachmentService(self.workspace).import_text(
            session.id, "def add(a, b): return a + b", "math.py"
        )
        response = self.client.post(
            "/api/chat",
            json={"model": "qwen", "prompt": "Review the attachment", "session_id": session.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ARCHIVE CONTENTS FROM math.py", self.service.last_prompt)
        self.assertIn("def add(a, b): return a + b", self.service.last_prompt)
        self.assertIn("BEGIN EXTRACTED REFERENCE DATA", self.service.last_prompt)
        restored = self.workspace.get_session(session.id)
        self.assertEqual([message.role for message in restored.messages], ["user", "assistant"])
        self.assertEqual(restored.messages[0].content, "Review the attachment")

    def test_session_chat_sends_original_images_to_vision_models(self):
        import io
        from PIL import Image
        from web_app.attachments import AttachmentService

        session = self.workspace.create_session()
        encoded = io.BytesIO()
        Image.new("RGB", (20, 10), "white").save(encoded, format="PNG")
        AttachmentService(self.workspace).import_stream(
            session.id, "screen.png", io.BytesIO(encoded.getvalue())
        )
        self.service.vision = True

        response = self.client.post(
            "/api/chat",
            json={"model": "qwen", "prompt": "Review the image", "session_id": session.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.service.last_images), 1)
        self.assertTrue(self.service.last_images[0].is_file())

    def test_conversion_prompt_creates_new_archive_and_returns_locations(self):
        from web_app.attachments import AttachmentService

        session = self.workspace.create_session()
        encoded = io.BytesIO()
        with zipfile.ZipFile(encoded, "w") as archive:
            archive.writestr("skills/example/SKILL.md", "# Claude skill")
        source = AttachmentService(self.workspace).import_stream(
            session.id,
            "claude-skills.zip",
            io.BytesIO(encoded.getvalue()),
        )
        original, _ = AttachmentService(self.workspace).original_path(session.id, source.id)
        response = self.client.post(
            "/api/chat",
            json={
                "model": "qwen",
                "session_id": session.id,
                "prompt": "Convert these Claude skills and save the updated files as a new ZIP archive",
            },
        )

        self.assertEqual(response.status_code, 200)
        artifact = response.json()["artifact"]
        self.assertEqual(artifact["filename"], "claude-skills-converted.zip")
        self.assertTrue(Path(artifact["path"]).is_file())
        self.assertTrue(artifact["url"].startswith("http://testserver/api/sessions/"))
        self.assertTrue(original.is_file())
        download = self.client.get(artifact["url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["content-type"], "application/zip")

    def test_unknown_model_is_rejected(self):
        response = self.client.post("/api/chat", json={"model": "missing", "prompt": "Hello"})
        self.assertEqual(response.status_code, 400)

    def test_unavailable_model_returns_conflict(self):
        response = self.client.post(
            "/api/chat", json={"model": "opencoder:8b", "prompt": "Hello"}
        )
        self.assertEqual(response.status_code, 409)

    def test_model_output_error_returns_stable_bad_gateway_envelope(self):
        self.service.error = ModelOutputError("Malformed structured output")
        response = self.client.post("/api/chat", json={"model": "qwen", "prompt": "Hello"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Malformed structured output")

    def test_timeout_returns_gateway_timeout(self):
        self.service.error = ModelTimeoutError("Model request timed out")
        response = self.client.post("/api/chat", json={"model": "qwen", "prompt": "Hello"})
        self.assertEqual(response.status_code, 504)

    def test_ollama_failure_returns_bad_gateway(self):
        self.service.error = OllamaUnavailableError("Ollama is unavailable")
        response = self.client.post("/api/chat", json={"model": "qwen", "prompt": "Hello"})
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
