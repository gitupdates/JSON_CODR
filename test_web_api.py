import asyncio
import json
import unittest
import tempfile
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from cli import parse_response_content
from web_app.models import ActionSuggestion, ChatResult, ConversionBundle, GeneratedFile
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaService, OllamaUnavailableError
from web_app.workspace import WorkspaceService


class FakeService:
    def __init__(self) -> None:
        self.available = True
        self.error = None
        self.last_prompt = None
        self.last_images = []
        self.vision = False
        self.actions = []

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
                actions=self.actions,
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


class FakeHardware:
    def __init__(self):
        self.probed = None
        self.benchmarked = None
        self.benchmark_error = None

    def status(self):
        return {"preferred_backend": "cpu", "last_known_good": "cpu", "quarantined": {}, "last_error": None}

    def detect(self):
        return [{"id": "cpu", "name": "CPU", "compatible": True, "verified": True}]

    async def probe(self, backend, model):
        self.probed = (backend, model)
        return {**self.status(), "preferred_backend": backend, "restart_required": True}

    def restore_cpu(self):
        return self.status()

    async def benchmark(self, suite, model, backend="all"):
        if self.benchmark_error:
            raise self.benchmark_error
        self.benchmarked = (suite, model, backend)
        return {"id": "run-1", "suite": suite, "model": model, "target_backend": backend, "results": []}

    def benchmark_history(self):
        return [{"id": "run-0", "suite": "quick", "model": "model", "results": []}]


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
        self.assertEqual(reopened.json()["schema_version"], 2)

        deleted = self.client.delete(f"/api/sessions/{session_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").status_code, 404)

    def test_session_path_traversal_is_rejected(self):
        response = self.client.get("/api/sessions/not-an-id")
        self.assertEqual(response.status_code, 400)

    def test_health_reports_ollama_readiness(self):
        self.assertEqual(
            self.client.get("/api/health").json(),
            {"status": "ready", "ollama": True, "app_version": "V1.0.5"},
        )
        self.assertEqual(self.client.app.version, "V1.0.5")
        self.service.available = False
        self.assertEqual(self.client.get("/api/health").json()["status"], "degraded")

    def test_hardware_detection_probe_and_cpu_restore_are_exposed(self):
        hardware = FakeHardware()
        client = TestClient(create_app(self.service, self.workspace, hardware=hardware))

        self.assertEqual(client.get("/api/hardware").json()["preferred_backend"], "cpu")
        self.assertEqual(client.post("/api/hardware/detect").json()[0]["id"], "cpu")
        response = client.post("/api/hardware/probe", json={"backend": "cpu", "model": "qwen2.5-coder:0.5b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hardware.probed, ("cpu", "qwen2.5-coder:0.5b"))
        self.assertEqual(client.post("/api/hardware/restore-cpu").json()["preferred_backend"], "cpu")

    def test_hardware_benchmark_execution_history_validation_and_busy_conflict(self):
        hardware = FakeHardware()
        client = TestClient(create_app(self.service, self.workspace, hardware=hardware))

        response = client.post(
            "/api/hardware/benchmarks",
            json={"suite": "quick", "model": "qwen2.5-coder:0.5b", "backend": "cuda_v12"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "run-1")
        self.assertEqual(hardware.benchmarked, ("quick", "qwen2.5-coder:0.5b", "cuda_v12"))
        self.assertEqual(client.get("/api/hardware/benchmarks").json()[0]["id"], "run-0")

        invalid = client.post("/api/hardware/benchmarks", json={"suite": "overnight", "model": "model"})
        self.assertEqual(invalid.status_code, 422)

        hardware.benchmark_error = RuntimeError("A hardware benchmark is already running")
        busy = client.post("/api/hardware/benchmarks", json={"suite": "quick", "model": "model"})
        self.assertEqual(busy.status_code, 409)
        self.assertIn("already running", busy.json()["detail"])

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

    def test_chat_recalculates_recommendations_and_returns_attachment_metadata(self):
        from web_app.models import SkillPack, SkillRecord
        from web_app.skills import SkillLibraryService

        SkillLibraryService(self.workspace.data_root).install(SkillPack(
            id="local", name="Local", source_format="generic", source_name="local.zip",
            skills=[SkillRecord(
                id="python-review", name="Python Review", description="Review Python code",
                content="CAPABILITIES: python review\nCHECK PYTHON CAREFULLY",
            )],
        ))
        self.client.close()
        self.client = TestClient(create_app(self.service, self.workspace))
        session = self.workspace.create_session()

        response = self.client.post(
            "/api/chat",
            json={
                "model": "qwen",
                "prompt": "Review this Python code",
                "session_id": session.id,
                "skill_recommendations": [{"reference": "stale:missing", "score": 999}],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["reference"] for item in body["attached_skills"]], ["local:python-review"])
        self.assertEqual(body["skill_recommendations"][0]["reference"], "local:python-review")
        self.assertIn("name: python", body["skill_recommendations"][0]["reasons"])
        self.assertNotIn("stale:missing", self.service.last_prompt)
        self.assertIn("CHECK PYTHON CAREFULLY", self.service.last_prompt)

    def test_structured_actions_ignore_prose_commands_drop_invalid_entries_and_server_own_risk(self):
        prose_only = parse_response_content(json.dumps({
            "status": "ready",
            "summary": "No action",
            "content": "```powershell\nRemove-Item -Recurse C:\\\\temp\n```",
        }))
        self.assertEqual(prose_only.actions, [])

        parsed = parse_response_content(json.dumps({
            "status": "ready",
            "summary": "Mixed",
            "content": "Text remains available",
            "actions": [
                {"command": "git status", "cwd": ".", "explanation": "Inspect", "risk": "normal", "approved": True},
                {"command": "bad\u0000command", "cwd": ".", "explanation": "Invalid"},
                {"command": "git diff", "cwd": ".", "explanation": "Inspect changes"},
            ],
        }))
        self.assertEqual(parsed.content, "Text remains available")
        self.assertEqual([action.command for action in parsed.actions], ["git status", "git diff"])
        self.assertNotIn("risk", parsed.actions[0].model_dump())
        self.assertNotIn("approved", parsed.actions[0].model_dump())

    def test_chat_creates_server_owned_action_proposals_only_for_structured_actions(self):
        session = self.workspace.create_session()
        self.service.actions = [ActionSuggestion(
            command="git status", cwd=str(Path.cwd()), explanation="Inspect repository"
        )]

        response = self.client.post(
            "/api/chat", json={"model": "qwen", "prompt": "Check status", "session_id": session.id}
        )

        self.assertEqual(response.status_code, 200)
        proposal = response.json()["action_proposals"][0]
        self.assertEqual(proposal["command"], "git status")
        self.assertEqual(proposal["risk"], "normal")
        self.assertNotIn("token", proposal)

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
        self.assertIn("attached_skills", response.json())
        self.assertIn("attached_skillsets", response.json())
        self.assertIn("skill_recommendations", response.json())
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
