import asyncio
import json
import unittest
import tempfile
import io
import os
import zipfile
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.app import configure_local_analysis_tools
from cli import parse_response_content
from web_app.models import ActionSuggestion, ChatResult, ConversionBundle, GeneratedFile
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaService, OllamaUnavailableError
from web_app.workspace import WorkspaceService
from web_app.coding_agents import CodingAgentService
from web_app.git_broker import GitBrokerService


class FakeService:
    def __init__(self) -> None:
        self.available = True
        self.error = None
        self.last_prompt = None
        self.last_images = []
        self.vision = False
        self.actions = []
        self.config = {"tool_fallback_model": "qwen3:4b"}

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

    async def running_models(self):
        return [{
            "name": "qwen2.5-coder:0.5b",
            "size": 398_000_000,
            "size_vram": 398_000_000,
            "processor": "100% GPU",
        }]

    async def supports_vision(self, model):
        return self.vision

    async def supports_tools(self, model):
        return model != "opencoder:8b"

    async def tool_compatibility(self, model):
        native = await self.supports_tools(model)
        effective = model if native else self.config["tool_fallback_model"]
        return {
            "requested_model": model,
            "advertised_tools": native,
            "native_tools_verified": native,
            "route": "native_verified" if native else "delegated_verified",
            "effective_tool_model": effective,
            "available": True,
        }

    async def generate_deterministic(self, model, messages, temperature=0.0):
        scenario = messages[0]["content"].split("SCENARIO_ID:", 1)[1].splitlines()[0].strip()
        outputs = {
            "anti-regression-memory": '{"wal":true,"timeout_seconds":30,"asyncio_lock":true,"semaphore_limit":25}',
            "multi-hop-graph": '{"required_isolator":"Type-D Optical Coupler","ambient_c":47,"limit_c":42,"exceeds_limit":true}',
            "sycophancy-resistance": '{"retain_lock":true,"gil_guarantees_atomicity":false}',
            "structural-boundary": '{"status":"locked","items":[1,2]}',
            "dimensional-proportion": '{"ratio":"16:9","is_4_3":false,"meets_16_9":true}',
        }
        return outputs[scenario]

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
        self.probe_result = None
        self.selected_benchmark = None

    def status(self):
        return {"preferred_backend": "cpu", "last_known_good": "cpu", "quarantined": {}, "last_error": None}

    def detect(self):
        return [{"id": "cpu", "name": "CPU", "compatible": True, "verified": True}]

    async def probe(self, backend, model):
        self.probed = (backend, model)
        return self.probe_result or {**self.status(), "preferred_backend": backend, "restart_required": True}

    def restore_cpu(self):
        return self.status()

    async def benchmark(self, suite, model, backend="all"):
        if self.benchmark_error:
            raise self.benchmark_error
        self.benchmarked = (suite, model, backend)
        return {"id": "run-1", "suite": suite, "model": model, "target_backend": backend, "selected_backend": "cpu", "results": []}

    def apply_benchmark_selection(self, benchmark):
        self.selected_benchmark = benchmark
        return {"preferred_backend": benchmark["selected_backend"]}

    def benchmark_history(self):
        return [{"id": "run-0", "suite": "quick", "model": "model", "results": []}]

    def gpu_telemetry(self):
        return [{"index": 0, "name": "RTX 4060", "memory_total": 8188, "memory_free": 7956}]


class FakeIntegrityBenchmark:
    def __init__(self):
        self.error = None
        self.runs = []

    async def run(self, suite, model):
        if self.error:
            raise self.error
        result = {"id": "integrity-1", "suite": suite, "model": model, "scores": {"integrity": 100, "comprehension": 100, "overall": 100}, "scenarios": []}
        self.runs.insert(0, result)
        return result

    def history(self):
        return self.runs


class WebApiTests(unittest.TestCase):
    def test_local_analysis_tools_are_loaded_for_sandbox_sessions(self):
        tools = self.workspace.data_root / "tools"
        ghidra = tools / "ghidra_12.1.4_PUBLIC"
        ghidra.mkdir(parents=True)
        previous = os.environ.pop("GHIDRA_INSTALL_DIR", None)
        try:
            configure_local_analysis_tools(self.workspace.data_root)
            self.assertEqual(Path(os.environ["GHIDRA_INSTALL_DIR"]), ghidra.resolve())
        finally:
            if previous is None:
                os.environ.pop("GHIDRA_INSTALL_DIR", None)
            else:
                os.environ["GHIDRA_INSTALL_DIR"] = previous

    def setUp(self):
        self.service = FakeService()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceService(Path(self.temporary_directory.name))
        self.client = TestClient(create_app(self.service, self.workspace))

    def test_coding_agent_grant_launch_and_failure_leave_direct_chat_available(self):
        class FakeTerminals:
            def __init__(self):
                self.plans = []

            def create_agent(self, plan):
                self.plans.append(plan)
                return {"id": "agent-terminal", "pid": 123, "shell": plan.tool, "cwd": plan.cwd, "status": "running"}

            def list(self):
                return []

        project = Path(self.temporary_directory.name) / "project"
        project.mkdir()
        terminals = FakeTerminals()
        agents = CodingAgentService(
            self.workspace.data_root,
            executable_finder=lambda name: f"C:/tools/{name}.exe" if name == "aider" else None,
        )
        client = TestClient(create_app(self.service, self.workspace, terminals=terminals, coding_agents=agents))
        headers = {"X-JSON-CODR": "1"}

        status = client.get("/api/coding-agents/status").json()
        self.assertEqual({item["id"]: item["installed"] for item in status["tools"]}, {"continue": False, "aider": True})
        grant = client.post("/api/coding-agents/grants", headers=headers, json={
            "project_root": str(project), "tool": "aider"
        })
        self.assertEqual(grant.status_code, 201)
        launched = client.post("/api/coding-agents/launch", headers=headers, json={
            "project_root": str(project), "tool": "aider", "model": "qwen2.5-coder:7b-instruct-q4_K_M",
            "mode": "interactive"
        })
        self.assertEqual(launched.status_code, 201)
        self.assertEqual(terminals.plans[0].tool, "aider")

        fallback = client.post("/api/coding-agents/launch", headers=headers, json={
            "project_root": str(project), "tool": "aider", "model": "opencoder:8b",
            "mode": "delegated", "prompt": "Inspect the project"
        })
        self.assertEqual(fallback.status_code, 201)
        self.assertTrue(fallback.json()["tool_fallback_used"])
        self.assertEqual(fallback.json()["requested_model"], "opencoder:8b")
        self.assertEqual(fallback.json()["effective_model"], "qwen3:4b")
        self.assertIn("ollama_chat/qwen3:4b", terminals.plans[1].argv)

        failed = client.post("/api/coding-agents/launch", headers=headers, json={
            "project_root": str(project), "tool": "continue", "model": "qwen2.5-coder:7b-instruct-q4_K_M",
            "mode": "interactive"
        })
        self.assertEqual(failed.status_code, 403)
        direct = client.post("/api/chat", json={"model": "qwen2.5-coder:7b-instruct-q4_K_M", "prompt": "fallback"})
        self.assertEqual(direct.status_code, 200)
        self.assertEqual(direct.json()["content"], "Answered: fallback")

    def test_broker_status_grant_execute_and_revoke_are_project_scoped(self):
        project = Path(self.temporary_directory.name) / "broker-project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        (project / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
        agents = CodingAgentService(self.workspace.data_root, executable_finder=lambda name: None)
        broker = GitBrokerService(self.workspace.data_root)
        client = TestClient(create_app(self.service, self.workspace, coding_agents=agents, git_broker=broker))
        headers = {"X-JSON-CODR": "1"}

        denied = client.post("/api/git-broker/grants", json={"project_root": str(project), "profile": "broker"})
        self.assertEqual(denied.status_code, 403)
        granted = client.post("/api/git-broker/grants", headers=headers, json={
            "project_root": str(project), "profile": "broker"
        })
        self.assertEqual(granted.status_code, 201)
        grant = granted.json()
        status = client.get("/api/git-broker/status", params={"project_root": str(project)})
        baseline = status.json()["repository"]["dirty_fingerprint"]
        executed = client.post("/api/git-broker/tasks", headers=headers, json={
            "model": "yi-coder:9b-chat", "grant_id": grant["id"],
            "request": {"schema_version": 1, "project_root": str(project),
                        "baseline_fingerprint": baseline, "actions": [{"kind": "status"}]},
        })
        self.assertEqual(executed.status_code, 201)
        self.assertEqual(executed.json()["status"], "completed")
        revoked = client.delete(f"/api/git-broker/grants/{grant['id']}", headers=headers)
        self.assertEqual(revoked.status_code, 200)
        rejected = client.post("/api/git-broker/tasks", headers=headers, json={
            "model": "yi-coder:9b-chat", "grant_id": grant["id"],
            "request": {"schema_version": 1, "project_root": str(project),
                        "baseline_fingerprint": baseline, "actions": [{"kind": "status"}]},
        })
        self.assertEqual(rejected.status_code, 403)

    def test_broker_adapter_runs_non_tool_model_without_native_tool_schema(self):
        class BrokerModelService(FakeService):
            async def chat(self, model, prompt, images=None):
                baseline = prompt.split("baseline_fingerprint='", 1)[1].split("'", 1)[0]
                project_root = prompt.split("project_root='", 1)[1].split("';", 1)[0]
                return ChatResult(
                    model=model, status="ready", summary="Broker action ready",
                    content=json.dumps({"schema_version": 1, "project_root": project_root,
                                        "baseline_fingerprint": baseline, "actions": [{"kind": "status"}]}),
                )

        project = Path(self.temporary_directory.name) / "adapter-project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        (project / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
        agents = CodingAgentService(self.workspace.data_root, executable_finder=lambda name: None)
        client = TestClient(create_app(BrokerModelService(), self.workspace, coding_agents=agents))
        headers = {"X-JSON-CODR": "1"}
        grant = client.post("/api/git-broker/grants", headers=headers, json={
            "project_root": str(project), "profile": "broker"
        }).json()

        response = client.post("/api/git-broker/adapter", headers=headers, json={
            "model": "yi-coder:9b-chat", "grant_id": grant["id"], "project_root": str(project),
            "prompt": "Inspect this repository",
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["compatibility"], "broker_adapter")
        self.assertEqual(response.json()["result"]["status"], "completed")
        self.assertNotIn("does not support tools", response.text)

    def test_optimized_connector_catalog_and_install_plans_are_additive(self):
        client = TestClient(create_app(self.service, self.workspace, optimized=True))

        models = client.get("/api/models").json()["models"]
        self.assertTrue(any(item["name"].startswith("openvino/") and not item["installed"] for item in models))
        catalog = client.get("/api/inference/catalog")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual({item["provider"] for item in catalog.json()}, {"openvino", "ryzen_ai"})
        plan = client.get("/api/inference/install-plan/openvino")
        self.assertEqual(plan.status_code, 200)
        self.assertIn("openvino-genai", plan.json()["command"])
        self.assertFalse(plan.json()["includes_driver"])

    def test_hardware_runtime_install_creates_reviewable_cli_proposal_without_drivers(self):
        client = TestClient(create_app(self.service, self.workspace, optimized=True))
        session_id = client.post("/api/sessions").json()["id"]

        response = client.post(f"/api/sessions/{session_id}/hardware/openvino/install-proposal")

        self.assertEqual(response.status_code, 200)
        proposal = response.json()[0]
        self.assertIn("openvino-genai==2025.4", proposal["command"])
        self.assertIn("isolated OpenVINO runtime", proposal["explanation"])
        self.assertNotIn("driver", proposal["command"].casefold())

    def test_provider_environment_statuses_are_exposed_independently(self):
        client = TestClient(create_app(self.service, self.workspace, optimized=True))

        response = client.get("/api/inference/environments")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["provider"] for item in response.json()},
            {"openvino", "ryzen_ai", "winml", "directml"},
        )
        self.assertTrue(all(item["status"] == "missing" for item in response.json()))

    def test_hardware_detection_includes_compatible_installed_models_on_each_runtime(self):
        response = self.client.post("/api/hardware/detect")

        self.assertEqual(response.status_code, 200)
        cpu = response.json()[0]
        self.assertEqual(cpu["id"], "cpu")
        self.assertEqual(len(cpu["compatible_models"]), 1)
        model = cpu["compatible_models"][0]
        self.assertEqual(model["model"], "qwen2.5-coder:7b-instruct-q4_K_M")
        self.assertEqual(model["status"], "runnable")
        self.assertEqual(model["evidence"], {"execution": "CPU"})
        self.assertEqual(model["agent_compatibility"]["tool_route"], "native_verified")
        self.assertTrue(model["agent_compatibility"]["continue_verified"])
        self.assertTrue(model["agent_compatibility"]["aider_verified"])

    def test_hardware_detection_stays_available_while_ollama_model_listing_is_busy(self):
        class BusyService(FakeService):
            async def list_models(self):
                raise OllamaUnavailableError("Ollama is unavailable")

        client = TestClient(create_app(BusyService(), self.workspace, hardware=FakeHardware()))

        response = client.post("/api/hardware/detect")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "cpu")
        self.assertEqual(response.json()[0]["compatible_models"], [])
        self.assertEqual(response.json()[0]["model_compatibility_error"], "Ollama is unavailable")

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
            {"status": "ready", "ollama": True, "app_version": "V1.0.17-beta.3"},
        )
        self.assertEqual(self.client.app.version, "V1.0.17-beta.3")
        self.service.available = False
        self.assertEqual(self.client.get("/api/health").json()["status"], "degraded")

    def test_app_construction_does_not_require_optional_integrity_capability(self):
        class MinimalService:
            async def health(self):
                return {"ollama": True}

            async def list_models(self):
                return []

        client = TestClient(create_app(MinimalService(), self.workspace))

        self.assertEqual(client.get("/").status_code, 200)
        response = client.post("/api/integrity-benchmarks", json={"suite": "quick", "model": "model"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("unavailable", response.json()["detail"])
        self.assertEqual(client.get("/api/integrity-benchmarks").json(), [])

    def test_hardware_detection_probe_and_cpu_restore_are_exposed(self):
        hardware = FakeHardware()
        client = TestClient(create_app(self.service, self.workspace, hardware=hardware))

        self.assertEqual(client.get("/api/hardware").json()["preferred_backend"], "cpu")
        self.assertEqual(client.post("/api/hardware/detect").json()[0]["id"], "cpu")
        response = client.post("/api/hardware/probe", json={"backend": "cpu", "model": "qwen2.5-coder:0.5b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hardware.probed, ("cpu", "qwen2.5-coder:0.5b"))
        self.assertEqual(client.post("/api/hardware/restore-cpu").json()["preferred_backend"], "cpu")

    def test_hardware_telemetry_combines_gpu_and_ollama_runtime_data(self):
        hardware = FakeHardware()
        client = TestClient(create_app(self.service, self.workspace, hardware=hardware))

        payload = client.get("/api/hardware/telemetry").json()

        self.assertEqual(payload["gpus"][0]["name"], "RTX 4060")
        self.assertEqual(payload["models"][0]["processor"], "100% GPU")

    def test_verified_ollama_gpu_probe_saves_gpu_preferred_model_profile(self):
        hardware = FakeHardware()
        hardware.probe_result = {
            **hardware.status(),
            "preferred_backend": "ollama_gpu",
            "verified": True,
            "gpu_percent": 100,
            "vram_bytes": 398_000_000,
            "evidence": "100% GPU",
            "restart_required": False,
        }
        client = TestClient(create_app(self.service, self.workspace, hardware=hardware))

        response = client.post(
            "/api/hardware/probe",
            json={"backend": "ollama_gpu", "model": "qwen2.5-coder:0.5b"},
        )

        self.assertEqual(response.status_code, 200)
        profile = client.get("/api/settings").json()["gpu_optimization"]["model_profiles"]["qwen2.5-coder:0.5b"]
        self.assertEqual(profile["mode"], "gpu_preferred")

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
        self.assertEqual(hardware.selected_benchmark["selected_backend"], "cpu")
        self.assertEqual(client.get("/api/hardware/benchmarks").json()[0]["id"], "run-0")

        cleared = client.delete("/api/hardware/benchmarks")
        self.assertEqual(cleared.status_code, 200)

        invalid = client.post("/api/hardware/benchmarks", json={"suite": "overnight", "model": "model"})
        self.assertEqual(invalid.status_code, 422)

        hardware.benchmark_error = RuntimeError("A hardware benchmark is already running")
        busy = client.post("/api/hardware/benchmarks", json={"suite": "quick", "model": "model"})
        self.assertEqual(busy.status_code, 409)
        self.assertIn("already running", busy.json()["detail"])

    def test_integrity_benchmark_execution_history_and_validation(self):
        response = self.client.post(
            "/api/integrity-benchmarks",
            json={"suite": "quick", "model": "qwen2.5-coder:7b-instruct-q4_K_M"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scores"]["overall"], 100.0)
        history = self.client.get("/api/integrity-benchmarks")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["id"], response.json()["id"])
        invalid = self.client.post(
            "/api/integrity-benchmarks", json={"suite": "overnight", "model": "model"}
        )
        self.assertEqual(invalid.status_code, 422)

    def test_integrity_benchmark_rejects_unavailable_model_and_busy_run(self):
        unavailable = self.client.post(
            "/api/integrity-benchmarks", json={"suite": "quick", "model": "opencoder:8b"}
        )
        self.assertEqual(unavailable.status_code, 409)
        self.assertIn("not installed", unavailable.json()["detail"])

        integrity = FakeIntegrityBenchmark()
        integrity.error = RuntimeError("An integrity benchmark is already running")
        client = TestClient(create_app(self.service, self.workspace, integrity=integrity))
        busy = client.post(
            "/api/integrity-benchmarks",
            json={"suite": "quick", "model": "qwen2.5-coder:7b-instruct-q4_K_M"},
        )
        self.assertEqual(busy.status_code, 409)
        self.assertIn("already running", busy.json()["detail"])

    def test_integrity_benchmark_maps_model_roster_outage_without_saving_a_run(self):
        class OfflineRosterService(FakeService):
            async def list_models(self):
                raise RuntimeError("Ollama offline")

        client = TestClient(create_app(OfflineRosterService(), self.workspace))
        response = client.post(
            "/api/integrity-benchmarks",
            json={"suite": "quick", "model": "qwen2.5-coder:7b-instruct-q4_K_M"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(client.get("/api/integrity-benchmarks").json(), [])

    def test_localperf_package_export_preview_and_import_are_private_by_default(self):
        from web_app.localperf.aggregate import aggregate_run
        from web_app.localperf.models import SampleRecord
        from web_app.localperf.storage import LocalPerfStorage

        storage = LocalPerfStorage(self.workspace.data_root)
        run = aggregate_run([SampleRecord(
            prompt_id="lp-01", repetition=1, success=True, generation_tokens_per_second=2,
            ttft_ms=5, peak_vram_mb=0, total_duration_ms=10, prompt_tokens=1,
            generated_tokens=1, output="ok",
        )], {"model":"model", "backend":"cpu", "hardware":{"serial":"secret"},
             "software":{"application":"JSON_CODR", "version":"V1.0.10"}}, "quick", 1)
        storage.save_run(run)
        exported = self.client.get(f"/api/localperf/packages/{run.evaluation_id}")
        self.assertEqual(exported.status_code, 200)
        self.assertIn(".localperf.zip", exported.headers["content-disposition"])
        preview = self.client.post("/api/localperf/packages/preview", content=exported.content,
                                   headers={"content-type":"application/octet-stream"})
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["contains_system_details"])
        imported = self.client.post("/api/localperf/packages/import", content=exported.content,
                                    headers={"content-type":"application/octet-stream"})
        self.assertEqual(imported.status_code, 201)
        self.assertFalse(imported.json()["retained_system_details"])

    def test_model_compatibility_and_explicit_remote_search_endpoints(self):
        client = TestClient(create_app(self.service, self.workspace, optimized=True))
        compatibility = client.get("/api/hardware/model-compatibility")
        self.assertEqual(compatibility.status_code, 200)
        cpu = next(item for item in compatibility.json() if item["backend"] == "cpu")
        self.assertTrue(any(model["model"] == "qwen2.5-coder:7b-instruct-q4_K_M" for model in cpu["models"]))
        search = client.get("/api/inference/models/search", params={"provider":"openvino", "q":"Qwen", "limit":5})
        self.assertEqual(search.status_code, 200)
        self.assertLessEqual(len(search.json()), 5)

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

    def test_running_models_reports_gpu_offload_from_vram_share(self):
        class RunningClient:
            async def ps(self):
                return {"models": [{
                    "name": "qwen2.5-coder:0.5b",
                    "size": 400_000_000,
                    "size_vram": 300_000_000,
                }]}

        models = asyncio.run(OllamaService(client=RunningClient()).running_models())

        self.assertEqual(models[0]["processor"], "75% GPU")
        self.assertEqual(models[0]["size_vram"], 300_000_000)

    def test_model_tool_support_uses_verified_probe_results(self):
        class CapabilityClient:
            async def show(self, model):
                return {"capabilities": ["completion", "tools"]}

        service = OllamaService(client=CapabilityClient())
        supported = asyncio.run(service.supports_tools("qwen3:8b"))
        advertised_but_unverified = asyncio.run(service.supports_tools("qwen2.5-coder:7b"))

        self.assertTrue(supported)
        self.assertFalse(advertised_but_unverified)

    def test_tool_compatibility_distinguishes_advertised_native_and_delegated(self):
        class CapabilityClient:
            async def show(self, model):
                return {"capabilities": ["completion", "tools"]}

        service = OllamaService(client=CapabilityClient())

        delegated = asyncio.run(service.tool_compatibility("qwen2.5-coder:7b"))
        native = asyncio.run(service.tool_compatibility("qwen3:8b"))

        self.assertEqual(delegated, {
            "requested_model": "qwen2.5-coder:7b",
            "advertised_tools": True,
            "native_tools_verified": False,
            "route": "delegated_verified",
            "effective_tool_model": "qwen3:4b",
            "available": True,
        })
        self.assertEqual(native, {
            "requested_model": "qwen3:8b",
            "advertised_tools": True,
            "native_tools_verified": True,
            "route": "native_verified",
            "effective_tool_model": "qwen3:8b",
            "available": True,
        })

    def test_tool_compatibility_reports_unavailable_without_verified_fallback(self):
        class CapabilityClient:
            async def show(self, model):
                return {"capabilities": ["completion"]}

        service = OllamaService(client=CapabilityClient())
        service.config["verified_tool_models"] = []
        service.config["tool_fallback_model"] = ""

        result = asyncio.run(service.tool_compatibility("opencoder:8b"))

        self.assertEqual(result["route"], "unavailable")
        self.assertIsNone(result["effective_tool_model"])
        self.assertFalse(result["available"])

    def test_deterministic_generation_uses_zero_temperature_and_raw_text(self):
        class DeterministicClient:
            def __init__(self):
                self.request = None

            async def list(self):
                return {"models": [{"name": "qwen2.5-coder:0.5b", "details": {}}]}

            async def chat(self, **request):
                self.request = request
                return {"message": {"content": "raw benchmark evidence"}}

        client = DeterministicClient()
        service = OllamaService(client=client)

        output = asyncio.run(service.generate_deterministic(
            "qwen2.5-coder:0.5b", [{"role": "user", "content": "test"}], 0.0
        ))

        self.assertEqual(output, "raw benchmark evidence")
        self.assertEqual(client.request["options"], {"temperature": 0.0, "num_predict": 512})
        self.assertNotIn("format", client.request)

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

    def test_structured_coding_agent_task_is_validated_for_user_review(self):
        parsed = parse_response_content(json.dumps({
            "status": "success",
            "summary": "Delegate the repository edit",
            "content": "Review the proposed coding-agent task before launch.",
            "coding_agent_tasks": [{
                "tool": "aider",
                "project_root": self.temporary_directory.name,
                "prompt": "Inspect the failing tests and make the smallest safe fix.",
            }],
        }))

        self.assertEqual(len(parsed.coding_agent_tasks), 1)
        self.assertEqual(parsed.coding_agent_tasks[0].tool, "aider")

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
