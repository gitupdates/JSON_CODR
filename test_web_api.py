import asyncio
import json
import sqlite3
import sys
import unittest
import tempfile
import io
import os
import zipfile
import subprocess
from contextlib import closing
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
    def test_all_model_run_routes_create_poll_cancel_export_search_and_protect_originals(self):
        session = self.workspace.create_session()
        created = self.client.post("/api/model-runs", json={
            "session_id": session.id,
            "prompt": "Compare implementations",
            "profile": "general",
            "request_key": "api-run-1",
        })
        self.assertEqual(created.status_code, 201)
        run_id = created.json()["run_id"]
        self.assertEqual(created.json()["roster"], ["qwen2.5-coder:7b-instruct-q4_K_M"])
        self.assertEqual(created.json()["unavailable_models"], ["opencoder:8b"])

        polled = self.client.get(f"/api/model-runs/{run_id}")
        self.assertEqual(polled.status_code, 200)
        result_id = polled.json()["results"][0]["result_id"]
        denied = self.client.get(f"/api/model-runs/{run_id}/results/{result_id}/original")
        self.assertEqual(denied.status_code, 403)
        allowed = self.client.get(
            f"/api/model-runs/{run_id}/results/{result_id}/original",
            headers={"X-JSON-CODR": "1"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("USER TASK (authoritative):\nCompare implementations", allowed.json()["content"])
        self.assertEqual(allowed.json()["provider_events"], [])
        for format_name, content_type in (("json", "application/json"), ("markdown", "text/markdown"), ("csv", "text/csv")):
            exported = self.client.get(f"/api/model-runs/{run_id}/export", params={"format": format_name})
            self.assertEqual(exported.status_code, 200)
            self.assertIn(content_type, exported.headers["content-type"])
        searched = self.client.get(f"/api/model-runs/{run_id}/search", params={"q": "Compare"})
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()[0]["source"], "original")
        cancelled = self.client.post(f"/api/model-runs/{run_id}/cancel")
        self.assertEqual(cancelled.status_code, 200)

    def test_model_run_idempotency_conflict_and_code_jury_profile(self):
        session = self.workspace.create_session()
        payload = {"session_id": session.id, "prompt": "Review", "profile": "code_jury", "request_key": "same"}
        first = self.client.post("/api/model-runs", json=payload)
        replay = self.client.post("/api/model-runs", json=payload)
        conflict = self.client.post("/api/model-runs", json={**payload, "prompt": "Changed"})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.json()["run_id"], first.json()["run_id"])
        self.assertEqual(first.json()["profile"], "code_jury")
        self.assertEqual(conflict.status_code, 409)

    def test_existing_chat_shape_adds_canonical_run_link(self):
        session = self.workspace.create_session()
        response = self.client.post("/api/chat", json={
            "model": "qwen",
            "prompt": "hello",
            "session_id": session.id,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("USER TASK (authoritative):\nhello", body["content"])
        self.assertEqual(body["summary"], "Ready")
        self.assertRegex(body["run_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(self.client.get(f"/api/model-runs/{body['run_id']}").status_code, 200)

    def test_manual_mcp_registration_is_exposed_through_core_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceService(Path(directory))
            (workspace.data_root / "mcp_servers.json").write_text(json.dumps({
                "mcpServers": {
                    "rea": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["D:/tools/rea.mjs", "mcp"],
                        "allowedTools": ["*"],
                    }
                }
            }), encoding="utf-8")
            with TestClient(create_app(FakeService(), workspace)) as client:
                capabilities = client.get("/api/capabilities").json()

            self.assertTrue(any(
                item["capability_id"] == "mcp.rea" and item["available"]
                for item in capabilities
            ))

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
        self._core_clients = [self.client]

    def test_github_routes_keep_authentication_server_side_and_require_write_confirmation(self):
        class FakeGitHubCLI:
            def __init__(self):
                self.writes = []

            def status(self):
                return {"authenticated": True, "login": "test-user"}

            def repositories(self):
                return [{"full_name": "test-user/sample", "private": True}]

            def branches(self, owner, repository):
                return [{"name": "main", "protected": True}]

            def commits(self, owner, repository):
                return [{"sha": "abc123", "message": "Test commit"}]

            def create_issue(self, owner, repository, title, body):
                self.writes.append((owner, repository, title, body))
                return {"number": 12, "title": title}

        github = FakeGitHubCLI()
        client = self.track_core_client(
            TestClient(create_app(self.service, self.workspace, github_cli=github))
        )
        headers = {"X-JSON-CODR": "1"}

        unauthorized = client.get("/api/github/status")
        status = client.get("/api/github/status", headers=headers)
        repositories = client.get("/api/github/repositories", headers=headers)
        branches = client.get("/api/github/repos/test-user/sample/branches", headers=headers)
        commits = client.get("/api/github/repos/test-user/sample/commits", headers=headers)
        unconfirmed = client.post(
            "/api/github/repos/test-user/sample/issues",
            headers=headers,
            json={"title": "Issue", "body": "Details"},
        )
        created = client.post(
            "/api/github/repos/test-user/sample/issues",
            headers=headers,
            json={"confirmed": True, "title": "Issue", "body": "Details"},
        )

        self.assertEqual(unauthorized.status_code, 403)
        self.assertEqual(status.json()["login"], "test-user")
        self.assertEqual(repositories.json()[0]["full_name"], "test-user/sample")
        self.assertEqual(branches.json()[0]["name"], "main")
        self.assertEqual(commits.json()[0]["sha"], "abc123")
        self.assertEqual(unconfirmed.status_code, 422)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(github.writes, [("test-user", "sample", "Issue", "Details")])

    def test_expanded_github_routes_require_confirmation_and_validate_repository_deletion(self):
        class FakeGitHubCLI:
            def __init__(self):
                self.writes = []

            def create_repository(self, *args):
                self.writes.append(("create_repository", args))
                return {"full_name": "test-user/new-repo"}

            def update_repository(self, *args):
                self.writes.append(("update_repository", args))
                return {"full_name": "test-user/sample"}

            def delete_repository(self, *args):
                self.writes.append(("delete_repository", args))
                return {"deleted": True}

            def create_branch(self, *args):
                self.writes.append(("create_branch", args))
                return {"branch": args[2]}

            def delete_branch(self, *args):
                self.writes.append(("delete_branch", args))
                return {"deleted": True}

            def update_release(self, *args):
                self.writes.append(("update_release", args))
                return {"id": args[2]}

            def delete_release(self, *args):
                self.writes.append(("delete_release", args))
                return {"deleted": True}

            def clone_local_repository(self, *args):
                self.writes.append(("clone_local_repository", args))
                return {"project_root": args[1], "status": "cloned"}

            def fetch_local_changes(self, *args):
                self.writes.append(("fetch_local_changes", args))
                return {"status": "fetched"}

            def pull_local_changes(self, *args):
                self.writes.append(("pull_local_changes", args))
                return {"status": "pulled"}

        github = FakeGitHubCLI()
        client = self.track_core_client(TestClient(create_app(self.service, self.workspace, github_cli=github)))
        headers = {"X-JSON-CODR": "1"}

        missing_confirmation = client.post(
            "/api/github/repositories",
            headers=headers,
            json={"name": "new-repo"},
        )
        created = client.post(
            "/api/github/repositories",
            headers=headers,
            json={"confirmed": True, "name": "new-repo"},
        )
        updated = client.patch(
            "/api/github/repos/test-user/sample",
            headers=headers,
            json={"confirmed": True, "description": "Updated"},
        )
        wrong_delete_confirmation = client.request(
            "DELETE",
            "/api/github/repos/test-user/sample",
            headers=headers,
            json={"confirmed": True, "confirm_name": "test-user/other"},
        )
        deleted = client.request(
            "DELETE",
            "/api/github/repos/test-user/sample",
            headers=headers,
            json={"confirmed": True, "confirm_name": "test-user/sample"},
        )
        branch = client.post(
            "/api/github/repos/test-user/sample/branches",
            headers=headers,
            json={"confirmed": True, "branch": "feature/one", "source_branch": "main"},
        )
        deleted_branch = client.request(
            "DELETE",
            "/api/github/repos/test-user/sample/branches/feature/one",
            headers=headers,
            json={"confirmed": True},
        )
        release = client.patch(
            "/api/github/repos/test-user/sample/releases/7",
            headers=headers,
            json={"confirmed": True, "name": "Updated"},
        )
        deleted_release = client.request(
            "DELETE",
            "/api/github/repos/test-user/sample/releases/7",
            headers=headers,
            json={"confirmed": True},
        )
        cloned = client.post(
            "/api/github/local/clone",
            headers=headers,
            json={"confirmed": True, "repository": "test-user/sample", "destination": "C:/work/sample"},
        )
        fetched = client.post(
            "/api/github/local/fetch",
            headers=headers,
            json={"confirmed": True, "project_root": "C:/work/sample"},
        )
        pulled = client.post(
            "/api/github/local/pull",
            headers=headers,
            json={"confirmed": True, "project_root": "C:/work/sample"},
        )

        self.assertEqual(missing_confirmation.status_code, 422)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(wrong_delete_confirmation.status_code, 422)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(branch.status_code, 201)
        self.assertEqual(deleted_branch.status_code, 200)
        self.assertEqual(release.status_code, 200)
        self.assertEqual(deleted_release.status_code, 200)
        self.assertEqual(cloned.status_code, 201)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(pulled.status_code, 200)
        self.assertEqual([name for name, _ in github.writes], [
            "create_repository", "update_repository", "delete_repository", "create_branch",
            "delete_branch", "update_release", "delete_release", "clone_local_repository",
            "fetch_local_changes", "pull_local_changes",
        ])

    def track_core_client(self, client):
        self._core_clients.append(client)
        return client

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
        client = self.track_core_client(
            TestClient(create_app(self.service, self.workspace, terminals=terminals, coding_agents=agents))
        )
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
        self.assertIn("USER TASK (authoritative):\nfallback", direct.json()["content"])

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
        client = self.track_core_client(
            TestClient(create_app(self.service, self.workspace, coding_agents=agents, git_broker=broker))
        )
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
        with closing(sqlite3.connect(self.workspace.data_root / "core" / "tasks.sqlite")) as database:
            durable_tasks = database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            durable_events = database.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        self.assertEqual(durable_tasks, 1)
        self.assertGreaterEqual(durable_events, 3)
        revoked = client.delete(f"/api/git-broker/grants/{grant['id']}", headers=headers)
        self.assertEqual(revoked.status_code, 200)
        rejected = client.post("/api/git-broker/tasks", headers=headers, json={
            "model": "yi-coder:9b-chat", "grant_id": grant["id"],
            "request": {"schema_version": 1, "project_root": str(project),
                        "baseline_fingerprint": baseline, "actions": [{"kind": "status"}]},
        })
        self.assertEqual(rejected.status_code, 403)

    def test_terminal_creation_is_recorded_by_core_service(self):
        class FakeTerminals:
            def create(self, shell, cwd):
                return type("Record", (), {
                    "id": "terminal-1", "pid": 123, "shell": shell, "cwd": str(cwd),
                    "status": "running", "external": False, "backend": "pipe",
                })()

            def close_all(self):
                pass

        project = Path(self.temporary_directory.name) / "terminal-project"
        project.mkdir()
        client = self.track_core_client(TestClient(create_app(self.service, self.workspace, terminals=FakeTerminals())))

        response = client.post(
            "/api/terminals",
            headers={"X-JSON-CODR": "1"},
            json={"shell": "powershell", "cwd": str(project)},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], "terminal-1")
        with closing(sqlite3.connect(self.workspace.data_root / "core" / "tasks.sqlite")) as database:
            command = database.execute("SELECT command_json FROM tasks").fetchone()[0]
            event_types = [
                json.loads(row[0])["event_type"]
                for row in database.execute("SELECT event_json FROM task_events ORDER BY sequence")
            ]
        self.assertIn('"command_type":"terminal.session"', command)
        self.assertIn("task.permission_required", event_types)
        self.assertIn("terminal.session_started", event_types)
        with closing(sqlite3.connect(self.workspace.data_root / "core" / "approvals.sqlite")) as database:
            approval_status = database.execute(
                "SELECT status FROM approval_proposals"
            ).fetchone()[0]
        self.assertEqual(approval_status, "consumed")

    def test_terminal_interrupt_and_close_are_recorded_by_core_service(self):
        class FakeTerminals:
            def __init__(self):
                self.interrupted = []
                self.closed = []

            def create(self, shell, cwd):
                return type("Record", (), {
                    "id": "terminal-1", "pid": 123, "shell": shell, "cwd": str(cwd),
                    "status": "running", "external": False, "backend": "pipe",
                })()

            def interrupt(self, terminal_id):
                self.interrupted.append(terminal_id)

            def close(self, terminal_id):
                self.closed.append(terminal_id)

            def close_all(self):
                pass

        project = Path(self.temporary_directory.name) / "terminal-lifecycle-project"
        project.mkdir()
        terminals = FakeTerminals()
        client = self.track_core_client(TestClient(create_app(self.service, self.workspace, terminals=terminals)))
        headers = {"X-JSON-CODR": "1"}
        created = client.post("/api/terminals", headers=headers, json={"cwd": str(project)})

        interrupted = client.post("/api/terminals/terminal-1/interrupt", headers=headers)
        closed = client.delete("/api/terminals/terminal-1", headers=headers)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(interrupted.status_code, 204)
        self.assertEqual(closed.status_code, 204)
        self.assertEqual(terminals.interrupted, ["terminal-1"])
        self.assertEqual(terminals.closed, ["terminal-1"])
        with closing(sqlite3.connect(self.workspace.data_root / "core" / "tasks.sqlite")) as database:
            commands = [row[0] for row in database.execute("SELECT command_json FROM tasks ORDER BY rowid")]
        self.assertEqual(len(commands), 3)
        self.assertIn('"command_type":"terminal.interrupt"', commands[1])
        self.assertIn('"command_type":"terminal.close"', commands[2])

    def test_ordinary_chat_generation_is_recorded_by_core_service(self):
        response = self.client.post("/api/chat", json={"model": "qwen", "prompt": "hello"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("USER TASK (authoritative):\nhello", response.json()["content"])
        with closing(sqlite3.connect(self.workspace.data_root / "core" / "tasks.sqlite")) as database:
            command = database.execute("SELECT command_json FROM tasks").fetchone()[0]
            event_types = [
                json.loads(row[0])["event_type"]
                for row in database.execute("SELECT event_json FROM task_events ORDER BY sequence")
            ]
        self.assertIn('"command_type":"inference.generate"', command)
        self.assertIn("inference.completed", event_types)

    def test_unified_task_submission_uses_real_session_skill_context(self):
        session_id = self.client.post("/api/sessions").json()["id"]
        task_id = "task-skill-context"
        response = self.client.post("/api/tasks", json={
            "schema_version": "1",
            "command_id": "command-skill-context",
            "task_id": task_id,
            "thread_id": f"thread-{session_id}",
            "project_id": f"project-{session_id}",
            "command_type": "capability.execute",
            "payload": {
                "capability_id": "inference.generate",
                "operation": "generate",
                "project_root": str(self.workspace.data_root),
                "mode": "native",
                "arguments": {
                    "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                    "prompt": "Plan an evidence-driven reverse-engineering workflow for an existing application.",
                    "session_id": session_id,
                    "attachments": [],
                },
            },
        })

        self.assertEqual(response.status_code, 200)
        completed = next(
            event for event in response.json()["events"] if event["event_type"] == "inference.completed"
        )
        result = completed["payload"]["result"]
        self.assertIn("USER TASK (authoritative):\nPlan an evidence-driven", self.service.last_prompt)
        self.assertIn("ATTACHED SKILL rea-agents:reverse-engineer-anything", self.service.last_prompt)
        self.assertEqual(result["attached_skillsets"], ["planning"])
        self.assertEqual(result["attached_skills"][0]["reference"], "rea-agents:reverse-engineer-anything")

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
        client = self.track_core_client(TestClient(create_app(BrokerModelService(), self.workspace, coding_agents=agents)))
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
        with closing(sqlite3.connect(self.workspace.data_root / "core" / "tasks.sqlite")) as database:
            commands = [row[0] for row in database.execute("SELECT command_json FROM tasks")]
        self.assertEqual(len(commands), 1)
        self.assertIn('"command_type":"git.execute"', commands[0])

    def test_project_workspace_read_only_run_does_not_create_persistent_broker_grant(self):
        class WorkspaceModelService(FakeService):
            def __init__(self):
                super().__init__()
                self.planner_calls = 0

            async def chat(self, model, prompt, images=None):
                baseline = prompt.split("baseline_fingerprint='", 1)[1].split("'", 1)[0]
                project_root = prompt.split("project_root='", 1)[1].split("';", 1)[0]
                return ChatResult(
                    model=model,
                    status="ready",
                    summary="Workspace action ready",
                    content=json.dumps({
                        "schema_version": 1,
                        "project_root": project_root,
                        "baseline_fingerprint": baseline,
                        "actions": [{"kind": "status"}],
                    }),
                )

        project = Path(self.temporary_directory.name) / "workspace-project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        (project / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
        agents = CodingAgentService(self.workspace.data_root, executable_finder=lambda name: None)
        client = self.track_core_client(TestClient(create_app(
            WorkspaceModelService(), self.workspace, coding_agents=agents,
        )))
        request = {
            "project_root": str(project),
            "model": "yi-coder:9b-chat",
            "outcome": "Inspect the repository and report its current status",
        }

        first = client.post("/api/project-workspace/run", headers={"X-JSON-CODR": "1"}, json=request)
        second = client.post("/api/project-workspace/run", headers={"X-JSON-CODR": "1"}, json=request)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["route"], "broker_adapter")
        self.assertEqual(first.json()["requested_model"], "yi-coder:9b-chat")
        self.assertEqual(first.json()["effective_model"], "yi-coder:9b-chat")
        self.assertEqual(first.json()["result"]["status"], "completed")
        self.assertEqual(second.status_code, 201)
        grants = [item for item in agents.status()["grants"] if item["profile"] == "broker"]
        self.assertEqual(grants, [])

    def test_project_workspace_rejects_model_generated_commit_without_granting_it(self):
        class CommittingModelService(FakeService):
            async def chat(self, model, prompt, images=None):
                baseline = prompt.split("baseline_fingerprint='", 1)[1].split("'", 1)[0]
                project_root = prompt.split("project_root='", 1)[1].split("';", 1)[0]
                patch = (
                    "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n"
                    "@@ -1 +1 @@\n-test\n+changed\n"
                )
                return ChatResult(model=model, status="ready", summary="Commit ready", content=json.dumps({
                    "schema_version": 1,
                    "project_root": project_root,
                    "baseline_fingerprint": baseline,
                    "actions": [
                        {"kind": "apply_patch", "patch": patch},
                        {"kind": "commit", "message": "Model commit"},
                    ],
                }))

        project = Path(self.temporary_directory.name) / "sensitive-workspace-project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        (project / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
        initial_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True,
        ).stdout.strip()
        agents = CodingAgentService(self.workspace.data_root, executable_finder=lambda name: None)
        client = self.track_core_client(TestClient(create_app(
            CommittingModelService(), self.workspace, coding_agents=agents,
        )))

        response = client.post("/api/project-workspace/run", headers={"X-JSON-CODR": "1"}, json={
            "project_root": str(project),
            "model": "yi-coder:9b-chat",
            "outcome": "Change and commit the README",
        })

        self.assertEqual(response.status_code, 409)
        self.assertIn("approval", response.json()["detail"].lower())
        self.assertEqual((project / "README.md").read_text(encoding="utf-8"), "test\n")
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(current_head, initial_head)
        self.assertEqual([item for item in agents.status()["grants"] if item["profile"] == "broker"], [])

    def test_project_workspace_rejects_missing_project_before_model_execution(self):
        response = self.client.post(
            "/api/project-workspace/run",
            headers={"X-JSON-CODR": "1"},
            json={
                "project_root": str(Path(self.temporary_directory.name) / "missing"),
                "model": "qwen3:4b",
                "outcome": "Inspect the project",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("existing directory", response.json()["detail"])

    def test_workspace_task_routes_explicit_auto_and_multi_model_selections(self):
        class WorkspaceModelService(FakeService):
            def __init__(self):
                super().__init__()
                self.planner_calls = 0

            async def list_models(self):
                return [*await super().list_models(), {
                    "name": "deepseek-coder:6.7b-instruct", "installed": True, "size": 1,
                    "quantization": "Q4", "context_length": 4096, "capabilities": ["completion"],
                }]

            async def supports_tools(self, model):
                return model == "qwen2.5-coder:7b-instruct-q4_K_M"

            async def chat(self, model, prompt, images=None):
                self.last_prompt = prompt
                if "Return one capability call" in prompt:
                    self.planner_calls += 1
                    if "agent.action_completed" not in prompt:
                        content = {
                            "done": False, "capability_id": "project.read", "operation": "read",
                            "target_path": "README.md", "arguments": {},
                        }
                    else:
                        content = {
                            "done": True, "capability_id": "project.read", "operation": "read",
                            "target_path": "README.md", "arguments": {},
                        }
                    return ChatResult(model=model, status="ready", summary="Plan", content=json.dumps(content))
                baseline = prompt.split("baseline_fingerprint='", 1)[1].split("'", 1)[0]
                project_root = prompt.split("project_root='", 1)[1].split("';", 1)[0]
                return ChatResult(model=model, status="ready", summary="Ready", content=json.dumps({
                    "schema_version": 1,
                    "project_root": project_root,
                    "baseline_fingerprint": baseline,
                    "actions": [{"kind": "status"}],
                }))

        project = Path(self.temporary_directory.name) / "canonical-workspace"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        (project / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
        model_service = WorkspaceModelService()
        client = self.track_core_client(TestClient(create_app(model_service, self.workspace)))
        session = self.workspace.create_session()
        from web_app.attachments import AttachmentService
        AttachmentService(self.workspace).import_text(session.id, "workspace context evidence")
        base = {
            "project_root": str(project), "session_id": session.id,
            "engine_id": "borg", "prompt": "Inspect the repository",
        }

        explicit = client.post("/api/workspace/tasks", json={**base, "model_selection": "qwen2.5-coder:7b-instruct-q4_K_M"})
        automatic = client.post("/api/workspace/tasks", json={**base, "model_selection": "auto"})
        multiple = client.post("/api/workspace/tasks", json={**base, "model_selection": "multi-model"})
        bad_engine = client.post("/api/workspace/tasks", json={**base, "engine_id": "missing", "model_selection": "auto"})
        bad_model = client.post("/api/workspace/tasks", json={**base, "model_selection": "opencoder:8b"})
        fallback = client.post("/api/workspace/tasks", json={**base, "model_selection": "deepseek-coder:6.7b-instruct"})
        missing_project = client.post("/api/workspace/tasks", json={
            **base, "project_root": str(project / "missing"), "model_selection": "auto",
        })

        self.assertEqual(explicit.status_code, 201, explicit.text)
        self.assertEqual(explicit.json()["requested_model"], "qwen2.5-coder:7b-instruct-q4_K_M")
        self.assertEqual(explicit.json()["effective_model"], "qwen2.5-coder:7b-instruct-q4_K_M")
        self.assertEqual(explicit.json()["requested_engine"], "borg")
        self.assertEqual(explicit.json()["effective_engine"], "borg")
        self.assertEqual(automatic.status_code, 201)
        self.assertEqual(automatic.json()["requested_model"], "auto")
        self.assertTrue(automatic.json()["warnings"])
        self.assertEqual(multiple.status_code, 202)
        self.assertEqual(multiple.json()["requested_model"], "multi-model")
        self.assertEqual(multiple.json()["route"], "multi-model")
        self.assertEqual(bad_engine.status_code, 409)
        self.assertEqual(bad_model.status_code, 409)
        self.assertEqual(fallback.status_code, 201)
        self.assertEqual(fallback.json()["requested_model"], "deepseek-coder:6.7b-instruct")
        self.assertEqual(fallback.json()["effective_model"], "qwen3:4b")
        self.assertTrue(fallback.json()["warnings"])
        self.assertIn("workspace context evidence", model_service.last_prompt)
        self.assertEqual(missing_project.status_code, 400)

    def test_optimized_connector_catalog_and_install_plans_are_additive(self):
        client = TestClient(create_app(self.service, self.workspace, optimized=True))

        self.assertEqual(type(client.app.state.model_runs.inference).__name__, "InferenceRouter")

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
        for client in self._core_clients:
            policy = getattr(client.app.state, "core_policy", None)
            task_store = getattr(client.app.state, "core_task_store", None)
            memory = getattr(client.app.state, "core_memory", None)
            approvals = getattr(client.app.state, "core_approval_store", None)
            projects = getattr(client.app.state, "core_project_registry", None)
            conformance = getattr(client.app.state, "core_model_conformance", None)
            if policy is not None:
                policy.close()
            if task_store is not None:
                task_store.close()
            if memory is not None:
                memory.close()
            if approvals is not None:
                approvals.close()
            if projects is not None:
                projects.close()
            if conformance is not None:
                conformance.close()
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
                {"status": "ready", "ollama": True, "app_version": "V1.2.0"},
        )
        self.assertEqual(self.client.app.version, "V1.2.0")
        self.service.available = False
        self.assertEqual(self.client.get("/api/health").json()["status"], "degraded")

    def test_ollama_health_allows_the_same_slow_local_response_as_model_discovery(self):
        class SlowLocalClient:
            async def list(self):
                await asyncio.sleep(2.1)
                return {"models": []}

        result = asyncio.run(OllamaService(client=SlowLocalClient()).health())

        self.assertEqual(result, {"ollama": True})

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

    def test_direct_chat_uses_the_same_authoritative_task_boundary_as_batch_runs(self):
        from web_app.attachments import AttachmentService

        session = self.workspace.create_session()
        AttachmentService(self.workspace).import_text(
            session.id,
            "This is stale test context and must not redefine current system capabilities.",
            "old-evidence.txt",
        )

        response = self.client.post(
            "/api/chat",
            json={"model": "qwen", "prompt": "Report current capabilities", "session_id": session.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("USER TASK (authoritative):\nReport current capabilities", self.service.last_prompt)
        self.assertIn("ACTIVE SKILLS AND REFERENCE CONTEXT:", self.service.last_prompt)
        self.assertIn("old-evidence.txt", self.service.last_prompt)
        self.assertIn("Keep facts from supplied context distinct", self.service.last_prompt)

    def test_production_agent_run_uses_core_service_and_verified_project_action(self):
        class PlannerService(FakeService):
            def __init__(self):
                super().__init__()
                self.plans = 0

            async def chat(self, model, prompt, images=None):
                if "Return one capability call" not in prompt:
                    return await super().chat(model, prompt, images)
                self.plans += 1
                content = (
                    json.dumps({
                        "done": False, "capability_id": "project.read", "operation": "read",
                        "target_path": "README.md", "arguments": {},
                    })
                    if self.plans == 1 else json.dumps({
                        "done": True, "capability_id": "project.read", "operation": "read",
                        "target_path": "README.md", "arguments": {},
                    })
                )
                return ChatResult(model=model, status="success", summary="plan", content=content)

        client = self.track_core_client(TestClient(create_app(PlannerService(), self.workspace)))
        response = client.post("/api/tasks", json={
            "schema_version": "1", "command_id": "agent-command", "task_id": "agent-task",
            "thread_id": "agent-thread", "project_id": "legacy", "command_type": "agent.run",
            "payload": {"goal_spec": {
                "schema_version": "1", "goal_id": "goal-1", "revision": 1,
                "objective": "Read the project README", "accepted": True,
                "criteria": [{
                    "schema_version": "1", "criterion_id": "read-completed",
                    "kind": "project_state", "description": "README was read through the project adapter",
                    "parameters": {},
                }],
            }},
        })

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        event_types = [event["event_type"] for event in body["events"]]
        self.assertIn("agent.action_completed", event_types)
        self.assertIn("agent.verified", event_types)

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
        self.client = self.track_core_client(TestClient(create_app(self.service, self.workspace)))
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

    def test_legacy_response_preserves_explicit_public_reasoning(self):
        parsed = parse_response_content(
            '<think>Check the repository evidence before answering.</think>'
            + json.dumps({
                "status": "ready",
                "summary": "Evidence checked",
                "content": "The public answer remains separate.",
            })
        )

        self.assertEqual(parsed.content, "The public answer remains separate.")
        self.assertEqual(len(parsed.reasoning.entries), 1)
        self.assertEqual(parsed.reasoning.entries[0].provenance, "provider_tag")
        self.assertEqual(
            parsed.reasoning.entries[0].text,
            "Check the repository evidence before answering.",
        )

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
