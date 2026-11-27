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
from unittest.mock import AsyncMock, patch
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from test_support import authenticated_client

from web_app.app import create_app
from web_app.app import configure_local_analysis_tools
from web_app.attachments import AttachmentService
from web_app.artifacts import ArtifactService
from cli import parse_response_content
from web_app.models import ActionSuggestion, ChatMessage, ChatResult, ConversionBundle, GeneratedFile, ObjectReference, SkillPack, SkillRecord
from web_app.core.memory import MemoryDraft
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaService, OllamaUnavailableError
from web_app.workspace import WorkspaceService
from web_app.skills import SkillLibraryService
from web_app.version import APP_VERSION
from web_app.coding_agents import CodingAgentService
from web_app.git_broker import GitBrokerService
from web_app.inference.contracts import ProbeResult, ProviderKind


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
    def test_owner_bound_session_route_families_enforce_one_authority_boundary(self):
        session_id = self.client.post("/api/sessions", json={}).json()["id"]
        attachment = AttachmentService(self.workspace).import_text(
            session_id, "authority evidence", "authority.txt"
        )
        artifact = ArtifactService(self.workspace).save_conversion(
            session_id,
            "authority.txt",
            [GeneratedFile(path="authority.txt", content="authority artifact")],
        )
        self.workspace.append_message(session_id, ChatMessage(
            role="assistant",
            content="owner evidence",
            references=[ObjectReference(
                id="authority-reference",
                kind="attachment",
                label="authority.txt",
                target=attachment.id,
            )],
        ))
        proposal_response = self.client.post(
            f"/api/sessions/{session_id}/hardware/openvino/install-proposal"
        )
        self.assertEqual(proposal_response.status_code, 200, proposal_response.text)
        proposal_id = proposal_response.json()[0]["id"]

        identity = self.client.app.state.identity
        foreign_user = identity.create_user(
            "session-route-foreign", "Session route foreign", roles=("administrator",)
        )
        foreign_browser_credential = identity.issue_credential(
            foreign_user.user_id,
            "browser_session",
            "foreign browser session routes",
            identity.browser_session_scopes(foreign_user.user_id),
        )
        foreign_browser = TestClient(self.client.app)
        foreign_browser.cookies.set("json_codr_session", foreign_browser_credential.token)
        self.assertEqual(foreign_browser.get("/api/identity/bootstrap").status_code, 200)
        foreign_browser.headers["X-CSRF-Token"] = foreign_browser.cookies.get("json_codr_csrf")
        foreign_bearer_credential = identity.issue_credential(
            foreign_user.user_id,
            "cli",
            "foreign bearer session routes",
            ("session.write", "terminal.write"),
        )
        foreign_bearer = TestClient(self.client.app)
        foreign_bearer.headers["Authorization"] = f"Bearer {foreign_bearer_credential.token}"
        foreign_wrong_scope_credential = identity.issue_credential(
            foreign_user.user_id,
            "cli",
            "foreign bearer wrong scope session routes",
            ("git.read",),
        )
        foreign_wrong_scope = TestClient(self.client.app)
        foreign_wrong_scope.headers["Authorization"] = (
            f"Bearer {foreign_wrong_scope_credential.token}"
        )
        anonymous = TestClient(self.client.app)
        try:
            read_paths = (
                f"/api/sessions/{session_id}",
                f"/api/sessions/{session_id}/conversation",
                f"/api/sessions/{session_id}/conversation/export?format=json",
                f"/api/sessions/{session_id}/references/authority-reference",
                f"/api/sessions/{session_id}/attachments",
                f"/api/sessions/{session_id}/artifacts/{artifact.filename}",
            )
            for path in read_paths:
                with self.subTest(family="read", path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)
                    self.assertEqual(foreign_browser.get(path).status_code, 404)
                    self.assertEqual(foreign_bearer.get(path).status_code, 404)
                    self.assertEqual(foreign_wrong_scope.get(path).status_code, 404)
                    self.assertEqual(anonymous.get(path).status_code, 404)

            mutations = (
                ("post", f"/api/sessions/{session_id}/conversation", {
                    "role": "assistant", "content": "owner-only append",
                }, 201),
                ("post", f"/api/sessions/{session_id}/clipboard-text", {
                    "text": "owner-only clipboard",
                }, 201),
                ("patch", f"/api/sessions/{session_id}/skill-routing", {
                    "auto_attach_skills": False,
                }, 200),
                ("patch", f"/api/sessions/{session_id}/skills", {
                    "selected": [],
                }, 200),
                ("post", f"/api/sessions/{session_id}/action-proposals/{proposal_id}/reject", None, 200),
            )
            for method, path, payload, owner_status in mutations:
                with self.subTest(family="mutation", path=path):
                    kwargs = {"json": payload} if payload is not None else {}
                    self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, owner_status)
                    self.assertEqual(getattr(foreign_browser, method)(path, **kwargs).status_code, 404)
                    self.assertEqual(getattr(foreign_bearer, method)(path, **kwargs).status_code, 404)
                    self.assertEqual(
                        getattr(foreign_wrong_scope, method)(path, **kwargs).status_code,
                        404,
                    )
                    self.assertEqual(getattr(anonymous, method)(path, **kwargs).status_code, 401)

            contents = [
                message.content for message in self.workspace.get_session(session_id).messages
            ]
            self.assertNotIn("FOREIGN_INJECTION", contents)
        finally:
            anonymous.close()
            foreign_wrong_scope.close()
            foreign_bearer.close()
            foreign_browser.close()

    def test_legacy_ownerless_session_routes_keep_explicit_compatibility_branch(self):
        session_id = self.client.post("/api/sessions").json()["id"]
        identity = self.client.app.state.identity
        foreign_user = identity.create_user(
            "legacy-session-writer", "Legacy session writer", roles=("administrator",)
        )
        credential = identity.issue_credential(
            foreign_user.user_id, "cli", "legacy session compatibility", ("session.write",)
        )
        bearer = TestClient(self.client.app)
        bearer.headers["Authorization"] = f"Bearer {credential.token}"
        anonymous = TestClient(self.client.app)
        try:
            self.assertEqual(anonymous.get(f"/api/sessions/{session_id}").status_code, 200)
            self.assertEqual(
                anonymous.get(f"/api/sessions/{session_id}/conversation").status_code,
                200,
            )
            appended = bearer.post(f"/api/sessions/{session_id}/conversation", json={
                "role": "assistant", "content": "legacy scoped writer",
            })
            self.assertEqual(appended.status_code, 201, appended.text)
        finally:
            anonymous.close()
            bearer.close()

    def test_session_delete_requires_same_owner_for_browser_and_bearer_clients(self):
        owner_bound = self.client.post("/api/sessions", json={})
        legacy_ownerless = self.client.post("/api/sessions")
        self.assertEqual((owner_bound.status_code, legacy_ownerless.status_code), (201, 201))
        owner_session_id = owner_bound.json()["id"]
        legacy_session_id = legacy_ownerless.json()["id"]

        identity = self.client.app.state.identity
        foreign_user = identity.create_user(
            "foreign-session-deleter", "Foreign session deleter", roles=("administrator",)
        )
        credential = identity.issue_credential(
            foreign_user.user_id, "cli", "foreign session delete", ("session.write",)
        )
        foreign = TestClient(self.client.app)
        foreign.headers["Authorization"] = f"Bearer {credential.token}"
        try:
            denied = foreign.delete(f"/api/sessions/{owner_session_id}")
            self.assertEqual(denied.status_code, 404)
            self.assertEqual(self.client.get(f"/api/sessions/{owner_session_id}").status_code, 200)

            legacy_deleted = foreign.delete(f"/api/sessions/{legacy_session_id}")
            self.assertEqual(legacy_deleted.status_code, 204)
        finally:
            foreign.close()

        owner_deleted = self.client.delete(f"/api/sessions/{owner_session_id}")
        self.assertEqual(owner_deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/sessions/{owner_session_id}").status_code, 404)

    def test_explicit_empty_session_request_is_owner_bound_and_can_be_promoted_on_save(self):
        project_root = Path(self.temporary_directory.name) / "promoted-history-project"
        project_root.mkdir()
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]

        legacy = self.client.post("/api/sessions")
        unassigned = self.client.post("/api/sessions", json={})

        self.assertEqual(legacy.status_code, 201)
        self.assertIsNone(legacy.json()["owner_user_id"])
        self.assertIsNone(legacy.json()["project_id"])
        self.assertEqual(unassigned.status_code, 201)
        self.assertEqual(
            unassigned.json()["owner_user_id"],
            self.client.app.state.identity.bootstrap_state().administrator_user_id,
        )
        self.assertIsNone(unassigned.json()["project_id"])

        saved = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": unassigned.json()["id"],
            "title": "Promoted browser session",
            "change_type": "feature",
            "keywords": ["session-promotion"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        promoted = self.client.get(f"/api/sessions/{unassigned.json()['id']}").json()
        self.assertEqual(promoted["project_id"], project_id)

    def test_project_session_api_binds_sessions_and_hides_foreign_snapshots(self):
        project_root = Path(self.temporary_directory.name) / "history-project"
        project_root.mkdir()
        resolved = self.client.post("/api/projects/resolve", json={"root": str(project_root)})

        self.assertEqual(resolved.status_code, 200)
        project_id = resolved.json()["project_id"]
        created = self.client.post("/api/sessions", json={"project_id": project_id})
        self.assertEqual(created.status_code, 201)
        session_id = created.json()["id"]
        session = self.workspace.get_session(session_id)
        self.assertEqual(session.project_id, project_id)
        self.assertEqual(session.owner_user_id, self.client.app.state.identity.bootstrap_state().administrator_user_id)

        self.workspace.append_message(session_id, ChatMessage(role="user", content="Preserve this implementation"))
        saved = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": session_id,
            "title": "Implementation review",
            "change_type": "feature",
            "keywords": ["history"],
        })
        self.assertEqual(saved.status_code, 200)
        snapshot_id = saved.json()["snapshot"]["id"]
        listing = self.client.get(f"/api/projects/{project_id}/sessions", params={"query": "history"})
        detail = self.client.get(f"/api/projects/{project_id}/sessions/{snapshot_id}")
        restored = self.client.post(f"/api/projects/{project_id}/sessions/{snapshot_id}/restore")

        self.assertEqual([item["id"] for item in listing.json()["snapshots"]], [snapshot_id])
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Objective: Preserve this implementation", detail.json()["history"])
        self.assertEqual(restored.status_code, 201)
        self.assertNotEqual(restored.json()["session_id"], session_id)

        other_project = Path(self.temporary_directory.name) / "other-history-project"
        other_project.mkdir()
        other_id = self.client.post("/api/projects/resolve", json={"root": str(other_project)}).json()["project_id"]
        before = {item.name for item in self.workspace.sessions_root.iterdir()}
        wrong_project = self.client.post(f"/api/projects/{other_id}/sessions/{snapshot_id}/restore")
        self.assertEqual(wrong_project.status_code, 404)
        self.assertEqual({item.name for item in self.workspace.sessions_root.iterdir()}, before)

        identity = self.client.app.state.identity
        other_user = identity.create_user("history-other", "History Other", roles=("administrator",))
        credential = identity.issue_credential(other_user.user_id, "cli", "history test", ("session.write",))
        foreign = TestClient(self.client.app)
        try:
            foreign.headers["Authorization"] = f"Bearer {credential.token}"
            before = {item.name for item in self.workspace.sessions_root.iterdir()}
            self.assertEqual(foreign.get(f"/api/projects/{project_id}/sessions/{snapshot_id}").status_code, 404)
            self.assertEqual(foreign.post(f"/api/projects/{project_id}/sessions/{snapshot_id}/restore").status_code, 404)
            self.assertEqual({item.name for item in self.workspace.sessions_root.iterdir()}, before)
        finally:
            foreign.close()

    def test_first_project_prompt_retrieves_history_and_persists_structured_provenance(self):
        project_root = Path(self.temporary_directory.name) / "retrieval-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        source_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        self.workspace.append_message(source_session, ChatMessage(
            role="user", content="Repair src/parser.py token handling"
        ))
        saved = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": source_session,
            "title": "Parser token repair",
            "change_type": "fix",
            "keywords": ["file:src/parser.py", "component:parser", "token-repair"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        snapshot_id = saved.json()["snapshot"]["id"]
        live_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]

        response = self.client.post("/api/chat", json={
            "model": "qwen",
            "prompt": "Explain the parser.py token repair",
            "session_id": live_session,
        })

        self.assertEqual(response.status_code, 200, response.text)
        source_ref = f"previous-session:{snapshot_id}"
        self.assertIn("PREVIOUS SESSION HISTORY", self.service.last_prompt)
        self.assertIn(source_ref, self.service.last_prompt)
        references = response.json()["references"]
        self.assertEqual([item["id"] for item in references], [source_ref])
        self.assertEqual(references[0]["kind"], "previous_session")
        messages = self.workspace.get_session(live_session).messages
        self.assertEqual(messages[-1].role, "assistant")
        self.assertEqual([item.id for item in messages[-1].references], [source_ref])

        identity = self.client.app.state.identity
        other = identity.create_user("history-reader-other", "Other", roles=("administrator",))
        token = identity.issue_credential(
            other.user_id, "cli", "history isolation", ("session.write", "agent.launch")
        ).token
        foreign = TestClient(self.client.app)
        foreign.headers["Authorization"] = f"Bearer {token}"
        try:
            denied = foreign.post("/api/chat", json={
                "model": "qwen",
                "prompt": "Explain the parser.py token repair",
                "session_id": live_session,
            })
            self.assertEqual(denied.status_code, 404)
        finally:
            foreign.close()

    def test_orphan_previous_session_projection_never_reaches_direct_or_native_model_context(self):
        project_root = Path(self.temporary_directory.name) / "orphan-history-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        session_id = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        owner_id = self.workspace.get_session(session_id).owner_user_id
        orphan_id = "e" * 32
        source_ref = f"previous-session:{orphan_id}"
        self.client.app.state.core_memory.accept(MemoryDraft(
            user_id=owner_id,
            project_id=project_id,
            thread_id="interrupted-source-session",
            task_id=orphan_id,
            kind="previous_session_history",
            content="Title: Orphan parser token\nKeywords: orphan-parser-token",
            source_refs=(source_ref,),
            idempotency_key=source_ref,
        ))

        direct = self.client.post("/api/chat", json={
            "model": "qwen",
            "prompt": "Explain orphan parser token",
            "session_id": session_id,
        })
        self.assertEqual(direct.status_code, 200, direct.text)
        self.assertNotIn(source_ref, self.service.last_prompt)
        self.assertEqual(direct.json()["references"], [])

        native = self.client.post("/api/tasks", json={
            "schema_version": "1",
            "command_id": "orphan-history-native-command",
            "task_id": "orphan-history-native-task",
            "thread_id": "orphan-history-native-thread",
            "project_id": project_id,
            "command_type": "capability.execute",
            "payload": {
                "capability_id": "inference.generate",
                "operation": "generate",
                "project_root": str(project_root),
                "mode": "native",
                "arguments": {
                    "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                    "prompt": "Explain orphan parser token",
                    "session_id": session_id,
                },
            },
        })
        self.assertEqual(native.status_code, 200, native.text)
        self.assertNotIn(source_ref, self.service.last_prompt)
        self.assertEqual(
            self.client.app.state.core_memory.search_collective(
                owner_id,
                project_id,
                "orphan parser token",
                kind="previous_session_history",
            ),
            (),
        )

    def test_foreign_principal_cannot_use_session_in_native_or_model_run_lifecycle(self):
        project_root = Path(self.temporary_directory.name) / "foreign-inference-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        session_id = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]

        owner_run = self.client.post("/api/model-runs", json={
            "session_id": session_id,
            "prompt": "owner-only model run",
            "profile": "general",
        })
        self.assertEqual(owner_run.status_code, 201, owner_run.text)
        run_id = owner_run.json()["run_id"]
        result_id = owner_run.json()["results"][0]["result_id"]

        identity = self.client.app.state.identity
        foreign_user = identity.create_user(
            "foreign-inference-user", "Foreign inference", roles=("administrator",)
        )
        token = identity.issue_credential(
            foreign_user.user_id,
            "cli",
            "foreign inference test",
            ("agent.launch", "session.write"),
        ).token
        foreign = TestClient(self.client.app)
        foreign.headers["Authorization"] = f"Bearer {token}"
        try:
            native = foreign.post("/api/tasks", json={
                "schema_version": "1",
                "command_id": "foreign-native-command",
                "task_id": "foreign-native-task",
                "thread_id": "foreign-native-thread",
                "project_id": project_id,
                "command_type": "capability.execute",
                "payload": {
                    "capability_id": "inference.generate",
                    "operation": "generate",
                    "project_root": str(project_root),
                    "mode": "native",
                    "arguments": {
                        "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                        "prompt": "disclose owner history",
                        "session_id": session_id,
                    },
                },
            })
            self.assertEqual(native.status_code, 404)
            self.assertEqual(
                foreign.post("/api/model-runs", json={
                    "session_id": session_id,
                    "prompt": "disclose owner history",
                    "profile": "general",
                }).status_code,
                404,
            )
            lifecycle = (
                foreign.get(f"/api/model-runs/{run_id}"),
                foreign.get(
                    f"/api/model-runs/{run_id}/results/{result_id}/original",
                    headers={"X-JSON-CODR": "1"},
                ),
                foreign.post(f"/api/model-runs/{run_id}/cancel"),
                foreign.get(f"/api/model-runs/{run_id}/export", params={"format": "json"}),
                foreign.get(f"/api/model-runs/{run_id}/search", params={"q": "owner"}),
            )
            self.assertEqual([response.status_code for response in lifecycle], [404] * 5)
        finally:
            foreign.close()

    def test_foreign_task_retry_cannot_trust_raw_principal_or_reach_session_history(self):
        project_root = Path(self.temporary_directory.name) / "retry-history-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        source_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        self.workspace.append_message(
            source_session,
            ChatMessage(role="user", content="Repair private-retry-parser-token"),
        )
        snapshot_id = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": source_session,
            "title": "Private retry parser repair",
            "change_type": "fix",
            "keywords": ["private-retry-parser-token"],
        }).json()["snapshot"]["id"]
        live_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        owner_id = self.workspace.get_session(live_session).owner_user_id

        def command(task_id, prompt, *, parent_task_id=None):
            body = {
                "schema_version": "1",
                "command_id": f"command-{task_id}",
                "task_id": task_id,
                "thread_id": "retry-history-thread",
                "project_id": project_id,
                "command_type": "capability.execute",
                "payload": {
                    "capability_id": "inference.generate",
                    "operation": "generate",
                    "project_root": str(project_root),
                    "mode": "native",
                    "arguments": {
                        "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                        "prompt": prompt,
                        "session_id": live_session,
                    },
                },
            }
            if parent_task_id is not None:
                body["parent_task_id"] = parent_task_id
            return body

        parent_id = "owner-retry-parent"
        parent = self.client.post(
            "/api/tasks",
            json=command(parent_id, "Explain private-retry-parser-token"),
        )
        self.assertEqual(parent.status_code, 200, parent.text)
        self.assertIn(f"previous-session:{snapshot_id}", self.service.last_prompt)

        identity = self.client.app.state.identity
        foreign_user = identity.create_user(
            "foreign-retry-user", "Foreign retry", roles=("administrator",)
        )
        foreign_token = identity.issue_credential(
            foreign_user.user_id,
            "cli",
            "foreign retry test",
            ("agent.launch",),
        ).token
        foreign = TestClient(self.client.app)
        foreign.headers.update({
            "Authorization": f"Bearer {foreign_token}",
            "X-JSON-CODR-Principal": owner_id,
        })
        try:
            attack_prompt = "FOREIGN RETRY MUST NOT REACH MODEL private-retry-parser-token"
            denied = foreign.post(
                f"/api/tasks/{parent_id}/retry",
                json=command("foreign-retry-child", attack_prompt, parent_task_id=parent_id),
            )

            self.assertEqual(denied.status_code, 404)
            self.assertNotIn(attack_prompt, self.service.last_prompt)
            self.assertNotIn("previous-session", denied.text)
        finally:
            foreign.close()

    def test_live_memory_disable_skips_retrieval_after_services_are_constructed(self):
        project_root = Path(self.temporary_directory.name) / "disabled-retrieval-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        source_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        self.workspace.append_message(
            source_session, ChatMessage(role="user", content="Repair disabled-memory-token")
        )
        saved = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": source_session,
            "title": "Disabled memory retrieval",
            "change_type": "fix",
            "keywords": ["disabled-memory-token"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        live_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]

        disabled = self.client.patch("/api/settings", json={
            "memory": {
                "enabled": False,
                "detailed_retention_enabled": False,
                "search_limit": 20,
            }
        })
        self.assertEqual(disabled.status_code, 200, disabled.text)
        response = self.client.post("/api/chat", json={
            "model": "qwen",
            "prompt": "Explain disabled-memory-token",
            "session_id": live_session,
        })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("PREVIOUS SESSION HISTORY", self.service.last_prompt)
        self.assertEqual(response.json()["references"], [])

    def test_direct_chat_assembles_previous_history_once_and_preserves_exact_provenance(self):
        project_root = Path(self.temporary_directory.name) / "single-build-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        source_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        self.workspace.append_message(source_session, ChatMessage(
            role="user", content="single-build-token"
        ))
        saved = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": source_session,
            "title": "Single build",
            "change_type": "fix",
            "keywords": ["single-build-token"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        snapshot_id = saved.json()["snapshot"]["id"]
        session_id = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        owner = self.workspace.get_session(session_id).owner_user_id
        record = self.client.app.state.core_memory.search_collective(
            owner,
            project_id,
            "single build token",
            kind="previous_session_history",
        )[0]
        calls = []

        def changing_search(*_args, **_kwargs):
            calls.append(len(calls) + 1)
            return (record,) if len(calls) == 1 else ()

        with patch.object(
            self.client.app.state.core_memory,
            "search_collective",
            side_effect=changing_search,
        ):
            response = self.client.post("/api/chat", json={
                "model": "qwen",
                "prompt": "single-build-token",
                "session_id": session_id,
            })

        source = f"previous-session:{snapshot_id}"
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls, [1])
        self.assertIn(source, self.service.last_prompt)
        self.assertEqual([item["id"] for item in response.json()["references"]], [source])
        self.assertEqual(
            [item.id for item in self.workspace.get_session(session_id).messages[-1].references],
            [source],
        )

    def test_history_retrieval_bypasses_unbound_sessions_and_survives_unavailable_memory(self):
        legacy_session = self.client.post("/api/sessions").json()["id"]
        response = self.client.post("/api/chat", json={
            "model": "qwen", "prompt": "parser.py", "session_id": legacy_session,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("PREVIOUS SESSION HISTORY", self.service.last_prompt)
        self.assertEqual(response.json()["references"], [])

        self.client.app.state.core_memory.close()
        response = self.client.post("/api/chat", json={
            "model": "qwen", "prompt": "parser.py", "session_id": legacy_session,
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_project_session_mutations_require_browser_csrf_but_allow_scoped_bearers(self):
        project_root = Path(self.temporary_directory.name) / "csrf-history-project"
        project_root.mkdir()
        self.client.headers.pop("X-CSRF-Token")
        rejected = self.client.post("/api/projects/resolve", json={"root": str(project_root)})

        self.assertEqual(rejected.status_code, 403)

        identity = self.client.app.state.identity
        owner_id = identity.bootstrap_state().administrator_user_id
        credential = identity.issue_credential(owner_id, "service", "history service", ("session.write",))
        bearer = TestClient(self.client.app)
        try:
            bearer.headers["Authorization"] = f"Bearer {credential.token}"
            accepted = bearer.post("/api/projects/resolve", json={"root": str(project_root)})
            self.assertEqual(accepted.status_code, 200)
        finally:
            bearer.close()

    def test_project_session_reads_require_identity_but_not_browser_csrf(self):
        project_root = Path(self.temporary_directory.name) / "read-history-project"
        project_root.mkdir()
        resolved = self.client.post("/api/projects/resolve", json={"root": str(project_root)})
        project_id = resolved.json()["project_id"]
        self.client.headers.pop("X-CSRF-Token")

        listing = self.client.get(f"/api/projects/{project_id}/sessions")

        self.assertEqual(listing.status_code, 200)
        unauthenticated = TestClient(self.client.app)
        try:
            self.assertEqual(unauthenticated.get(f"/api/projects/{project_id}/sessions").status_code, 401)
        finally:
            unauthenticated.close()

    def test_project_history_detail_is_opaque_when_history_is_missing_or_tampered(self):
        project_root = Path(self.temporary_directory.name) / "unsafe-history-project"
        project_root.mkdir()
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]
        session_id = self.client.post("/api/sessions", json={"project_id": project_id}).json()["id"]
        self.workspace.append_message(session_id, ChatMessage(role="user", content="keep this private"))
        snapshot_id = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": session_id, "title": "Safe history", "change_type": "fix",
        }).json()["snapshot"]["id"]
        history = self.workspace.data_root / "project-sessions"
        history = next(history.iterdir()) / "sessions" / snapshot_id / "previous-session-history.md"

        for replacement in ("tampered", None):
            if replacement is None:
                history.unlink()
            else:
                history.write_text(replacement, encoding="utf-8")
            response = self.client.get(f"/api/projects/{project_id}/sessions/{snapshot_id}")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "Project session is incomplete or unsafe"})
            self.assertNotIn(str(self.workspace.data_root), response.text)

    def test_project_session_save_does_not_depend_on_closed_memory_projection(self):
        project_root = Path(self.temporary_directory.name) / "projection-history-project"
        project_root.mkdir()
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]
        session_id = self.client.post("/api/sessions", json={"project_id": project_id}).json()["id"]
        self.client.app.state.core_memory.close()

        saved = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": session_id, "title": "No projection", "change_type": "fix",
        })

        self.assertEqual(saved.status_code, 200)
        snapshots = self.client.get(f"/api/projects/{project_id}/sessions").json()["snapshots"]
        self.assertEqual(len(snapshots), 1)

    def test_project_history_api_reads_exact_prior_format_snapshot(self):
        project_root = Path(self.temporary_directory.name) / "legacy-history-project"
        project_root.mkdir()
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]
        session_id = self.client.post("/api/sessions", json={"project_id": project_id}).json()["id"]
        snapshot_id = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": session_id, "title": "Legacy", "change_type": "fix",
        }).json()["snapshot"]["id"]
        snapshot = next((self.workspace.data_root / "project-sessions").iterdir()) / "sessions" / snapshot_id / "snapshot.json"
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("history_digest_version"), 1)
        payload.pop("history_digest_version")
        payload["tree_digests"].pop("previous-session-history.md")
        snapshot.write_text(json.dumps(payload), encoding="utf-8")

        detail = self.client.get(f"/api/projects/{project_id}/sessions/{snapshot_id}")
        restored = self.client.post(f"/api/projects/{project_id}/sessions/{snapshot_id}/restore")

        self.assertEqual(detail.status_code, 200)
        self.assertIn("Title: Legacy", detail.json()["history"])
        self.assertEqual(restored.status_code, 201)

    def test_project_history_api_rejects_modern_snapshot_without_required_digest_before_restore(self):
        project_root = Path(self.temporary_directory.name) / "modern-history-project"
        project_root.mkdir()
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]
        session_id = self.client.post("/api/sessions", json={"project_id": project_id}).json()["id"]
        snapshot_id = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": session_id, "title": "Modern", "change_type": "fix",
        }).json()["snapshot"]["id"]
        snapshot = next((self.workspace.data_root / "project-sessions").iterdir()) / "sessions" / snapshot_id / "snapshot.json"
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("history_digest_version"), 1)
        payload["tree_digests"].pop("previous-session-history.md")
        snapshot.write_text(json.dumps(payload), encoding="utf-8")
        before = {path.name for path in self.workspace.sessions_root.iterdir()}

        detail = self.client.get(f"/api/projects/{project_id}/sessions/{snapshot_id}")
        restored = self.client.post(f"/api/projects/{project_id}/sessions/{snapshot_id}/restore")

        self.assertEqual(detail.status_code, 400)
        self.assertEqual(restored.status_code, 400)
        self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)

    def test_project_session_mutation_matrix_keeps_scope_and_restored_references(self):
        project_root = Path(self.temporary_directory.name) / "matrix-project"
        project_root.mkdir()
        source = project_root / "bound.py"
        source.write_text("bound = True", encoding="utf-8")
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]
        legacy = self.client.post("/api/sessions")
        self.assertIsNone(legacy.json()["project_id"])
        self.assertIsNone(legacy.json()["owner_user_id"])
        for payload, expected in (({"project_id": ""}, 422), ({"project_id": "project:missing"}, 404)):
            self.assertEqual(self.client.post("/api/sessions", json=payload).status_code, expected)

        session_id = self.client.post("/api/sessions", json={"project_id": project_id}).json()["id"]
        attachment = AttachmentService(self.workspace).import_text(session_id, "attachment continuity", "note.txt")
        artifact = ArtifactService(self.workspace).save_conversion(session_id, "note.txt", [GeneratedFile(path="result.txt", content="artifact continuity")])
        self.workspace.append_message(session_id, ChatMessage(role="assistant", content="references", references=[
            ObjectReference(id="attachment", kind="attachment", label="note.txt", target=attachment.id),
            ObjectReference(id="artifact", kind="artifact", label=artifact.filename, target=artifact.filename),
            ObjectReference(id="project", kind="project_file", label="bound.py", target="bound.py"),
        ]))
        snapshot_id = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": session_id, "title": "Matrix", "change_type": "feature",
        }).json()["snapshot"]["id"]
        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        for suffix, expected in (("bad", 422), ("0" * 32, 404)):
            for method in ("get", "post"):
                path = f"/api/projects/{project_id}/sessions/{suffix}" + ("/restore" if method == "post" else "")
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, expected)
                if expected == 404:
                    self.assertEqual(response.json(), {"detail": "Project session not found"})
        self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)

        identity = self.client.app.state.identity
        other = identity.create_user("matrix-other", "Matrix Other", roles=("administrator",))
        token = identity.issue_credential(other.user_id, "cli", "matrix", ("session.write",)).token
        foreign = TestClient(self.client.app)
        foreign.headers["Authorization"] = f"Bearer {token}"
        try:
            self.assertEqual(foreign.get(f"/api/projects/{project_id}/sessions").json()["snapshots"], [])
            for method, path in (("post", f"/api/projects/{project_id}/sessions"), ("get", f"/api/projects/{project_id}/sessions/{snapshot_id}"), ("post", f"/api/projects/{project_id}/sessions/{snapshot_id}/restore")):
                kwargs = {"json": {"session_id": session_id, "title": "foreign", "change_type": "fix"}} if path.endswith("sessions") else {}
                response = getattr(foreign, method)(path, **kwargs)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Project session not found"})
        finally:
            foreign.close()

        restored = self.client.post(f"/api/projects/{project_id}/sessions/{snapshot_id}/restore").json()["session_id"]
        self.assertEqual(self.client.get(f"/api/sessions/{restored}/references/attachment").content, b"attachment continuity")
        self.assertTrue(self.client.get(f"/api/sessions/{restored}/references/artifact").content.startswith(b"PK"))
        self.assertEqual(self.client.get(f"/api/sessions/{restored}/references/project").content, b"bound = True")
        self.assertIs(self.client.app.state.project_sessions.projects, self.client.app.state.core_project_registry)

    def test_project_session_browser_csrf_and_bearer_matrix(self):
        project_root = Path(self.temporary_directory.name) / "auth-matrix-project"
        project_root.mkdir()
        project_id = self.client.post("/api/projects/resolve", json={"root": str(project_root)}).json()["project_id"]
        csrf = self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post("/api/sessions", json={"project_id": project_id}).status_code, 403)
        self.client.headers["X-CSRF-Token"] = csrf
        identity = self.client.app.state.identity
        owner = identity.bootstrap_state().administrator_user_id
        token = identity.issue_credential(owner, "service", "matrix", ("session.write",)).token
        bearer = TestClient(self.client.app)
        bearer.headers["Authorization"] = f"Bearer {token}"
        try:
            session_id = bearer.post("/api/sessions", json={"project_id": project_id}).json()["id"]
            snapshot_id = bearer.post(f"/api/projects/{project_id}/sessions", json={"session_id": session_id, "title": "Bearer", "change_type": "fix"}).json()["snapshot"]["id"]
            self.assertEqual(bearer.get(f"/api/projects/{project_id}/sessions/{snapshot_id}").status_code, 200)
            self.assertEqual(bearer.post(f"/api/projects/{project_id}/sessions/{snapshot_id}/restore").status_code, 201)
        finally:
            bearer.close()

    def test_openai_compatible_models_and_chat_routes_use_live_service(self):
        models = self.client.get("/v1/models")
        self.assertEqual(models.status_code, 200)
        self.assertEqual(models.json()["object"], "list")
        self.assertEqual(models.json()["data"][0]["id"], "qwen2.5-coder:7b-instruct-q4_K_M")

        response = self.client.post("/v1/chat/completions", json={
            "model": "qwen",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "qwen2.5-coder:7b-instruct-q4_K_M")
        self.assertEqual(body["choices"][0]["message"]["content"], "Answered: hello")
        self.assertNotIn("usage", body)

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
            with authenticated_client(create_app(FakeService(), workspace)) as client:
                capabilities = client.get("/api/capabilities").json()

            self.assertTrue(any(
                item["capability_id"] == "mcp.rea.discover" and item["available"]
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
        self.client = authenticated_client(create_app(self.service, self.workspace))
        self._core_clients = [self.client]

    def test_identity_bootstrap_returns_csrf_token_and_administrator_username(self):
        response = self.client.get("/api/identity/bootstrap")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["administrator_username"], "Administrator")
        self.assertEqual(payload["csrf_token"], self.client.cookies.get("json_codr_csrf"))

    def test_well_known_discovery_does_not_trust_an_arbitrary_host(self):
        response = self.client.get("/.well-known/json-codr", headers={"host": "attacker.example"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Host header must use loopback")

    def test_vscode_language_model_config_exposes_each_installed_model(self):
        response = self.client.get("/api/integrations/vscode/language-models")

        self.assertEqual(response.status_code, 200)
        provider = response.json()[0]
        self.assertEqual(provider["name"], "JSON_CODR")
        self.assertEqual(provider["vendor"], "customendpoint")
        self.assertTrue(provider["models"])
        self.assertTrue(all(model["id"] and model["name"] for model in provider["models"]))

    def test_external_model_exports_exclude_quarantined_and_keep_untested_models(self):
        class CompatibilityRosterService(FakeService):
            async def list_models(self):
                return [
                    {"name": "ready:1b", "installed": True, "runnable": True},
                    {"name": "untested:1b", "installed": True, "runnable": None},
                    {"name": "quarantined:1b", "installed": True, "runnable": False},
                ]

            async def model_metadata(self, model):
                return {"context_length": 2048, "tool_calling": False, "vision": False}

        client = self.track_core_client(authenticated_client(create_app(
            CompatibilityRosterService(), self.workspace, optimized=False,
        )))

        openai = client.get("/v1/models")
        vscode = client.get("/api/integrations/vscode/language-models")

        self.assertEqual(
            [item["id"] for item in openai.json()["data"]],
            ["ready:1b", "untested:1b"],
        )
        self.assertEqual(
            [item["id"] for item in vscode.json()[0]["models"]],
            ["ready:1b", "untested:1b"],
        )

    def test_github_routes_keep_authentication_server_side_and_require_write_confirmation(self):
        class FakeGitHubCLI:
            def __init__(self):
                self.writes = []
                self.commit_reads = []

            def status(self):
                return {"authenticated": True, "login": "test-user"}

            def repositories(self):
                return [{"full_name": "test-user/sample", "private": True}]

            def branches(self, owner, repository):
                return [{"name": "main", "protected": True}]

            def commits(self, owner, repository, branch=None):
                self.commit_reads.append((owner, repository, branch))
                return [{"sha": "abc123", "message": "Test commit"}]

            def create_issue(self, owner, repository, title, body):
                self.writes.append((owner, repository, title, body))
                return {"number": 12, "title": title}

        github = FakeGitHubCLI()
        client = self.track_core_client(
            authenticated_client(create_app(self.service, self.workspace, github_cli=github))
        )
        headers = {"X-JSON-CODR": "1"}

        with TestClient(client.app) as anonymous:
            unauthorized = anonymous.get("/api/github/status")
        status = client.get("/api/github/status", headers=headers)
        repositories = client.get("/api/github/repositories", headers=headers)
        branches = client.get("/api/github/repos/test-user/sample/branches", headers=headers)
        commits = client.get("/api/github/repos/test-user/sample/commits", headers=headers)
        branch_commits = client.get(
            "/api/github/repos/test-user/sample/commits?branch=feature%2Fui", headers=headers,
        )
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

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(status.json()["login"], "test-user")
        self.assertEqual(repositories.json()[0]["full_name"], "test-user/sample")
        self.assertEqual(branches.json()[0]["name"], "main")
        self.assertEqual(commits.json()[0]["sha"], "abc123")
        self.assertEqual(branch_commits.json()[0]["sha"], "abc123")
        self.assertEqual(github.commit_reads, [
            ("test-user", "sample", None),
            ("test-user", "sample", "feature/ui"),
        ])
        self.assertEqual(unconfirmed.status_code, 422)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(github.writes, [("test-user", "sample", "Issue", "Details")])

    def test_github_authentication_session_routes_are_confirmed_and_server_managed(self):
        from web_app.github_auth import GitHubAuthSessionConflict, GitHubAuthSessionNotFound

        class FakeGitHubAuth:
            def __init__(self):
                self.started = 0
                self.cancelled = []
                self.closed = False

            def start(self):
                self.started += 1
                if self.started > 1:
                    raise GitHubAuthSessionConflict("A GitHub login is already active")
                return {"session_id": "login-1", "state": "starting", "detail": "Starting"}

            def status(self, session_id):
                if session_id == "missing":
                    raise GitHubAuthSessionNotFound(session_id)
                return {
                    "session_id": session_id,
                    "state": "waiting",
                    "detail": "Complete sign-in",
                    "device_code": "ABCD-1234",
                    "verification_url": "https://github.com/login/device",
                }

            def cancel(self, session_id):
                self.cancelled.append(session_id)
                return {"session_id": session_id, "state": "cancelled", "detail": "Cancelled"}

            def close(self):
                self.closed = True

        auth = FakeGitHubAuth()
        headers = {"X-JSON-CODR": "1"}
        with authenticated_client(create_app(self.service, self.workspace, github_auth=auth)) as client:
            with TestClient(client.app) as anonymous:
                self.assertEqual(
                    anonymous.post("/api/github/auth/login", json={"confirmed": True}).status_code,
                    401,
                )
                self.assertEqual(anonymous.get("/api/github/auth/login/login-1").status_code, 401)
            self.assertEqual(client.post("/api/github/auth/login", headers=headers, json={}).status_code, 422)
            started = client.post(
                "/api/github/auth/login", headers=headers, json={"confirmed": True},
            )
            conflict = client.post(
                "/api/github/auth/login", headers=headers, json={"confirmed": True},
            )
            self.assertEqual(client.get("/api/github/auth/login/login-1").status_code, 200)
            waiting = client.get("/api/github/auth/login/login-1", headers=headers)
            missing = client.get("/api/github/auth/login/missing", headers=headers)
            self.assertEqual(
                client.post("/api/github/auth/login/login-1/cancel", headers=headers, json={}).status_code,
                422,
            )
            cancelled = client.post(
                "/api/github/auth/login/login-1/cancel",
                headers=headers,
                json={"confirmed": True},
            )

            self.assertEqual(started.status_code, 200)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(waiting.json()["device_code"], "ABCD-1234")
            self.assertEqual(waiting.json()["verification_url"], "https://github.com/login/device")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(cancelled.json()["state"], "cancelled")
            self.assertEqual(auth.cancelled, ["login-1"])
        self.assertTrue(auth.closed)

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
        client = self.track_core_client(authenticated_client(create_app(self.service, self.workspace, github_cli=github)))
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

    def test_github_build_check_and_update_require_confirmation_and_exact_scope(self):
        from web_app.github_cli import GitHubBuildConflict

        class FakeGitHubCLI:
            def __init__(self):
                self.calls = []

            def check_build(self, *args):
                self.calls.append(("check", args))
                return {
                    "repository": args[1], "branch": args[2], "status": "behind",
                    "local_commit": {"sha": "a" * 40},
                    "remote_commit": {"sha": "b" * 40},
                    "update_allowed": True,
                }

            def update_build(self, *args):
                self.calls.append(("update", args))
                if args[3] == "c" * 40:
                    raise GitHubBuildConflict("The build changed. Check again.")
                return {
                    "repository": args[1], "branch": args[2], "status": "current",
                    "local_commit": {"sha": args[4]},
                    "remote_commit": {"sha": args[4]},
                    "update_allowed": False,
                }

        github = FakeGitHubCLI()
        client = self.track_core_client(
            authenticated_client(create_app(self.service, self.workspace, github_cli=github))
        )
        headers = {"X-JSON-CODR": "1"}
        check_body = {
            "confirmed": True,
            "project_root": "C:/work/sample",
            "repository": "test-user/sample",
            "branch": "feature/ui",
        }
        with TestClient(client.app) as anonymous:
            self.assertEqual(anonymous.post("/api/github/local/check-build", json=check_body).status_code, 401)
        self.assertEqual(
            client.post(
                "/api/github/local/check-build",
                headers=headers,
                json={key: value for key, value in check_body.items() if key != "confirmed"},
            ).status_code,
            422,
        )
        checked = client.post("/api/github/local/check-build", headers=headers, json=check_body)
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.json()["status"], "behind")
        self.assertEqual(
            github.calls[0],
            ("check", ("C:/work/sample", "test-user/sample", "feature/ui")),
        )

        invalid_repository = client.post(
            "/api/github/local/check-build",
            headers=headers,
            json={**check_body, "repository": "not-a-repository"},
        )
        invalid_branch = client.post(
            "/api/github/local/check-build",
            headers=headers,
            json={**check_body, "branch": ""},
        )
        invalid_sha = client.post(
            "/api/github/local/update-build",
            headers=headers,
            json={**check_body, "expected_local_sha": "abc", "expected_remote_sha": "b" * 40, "expected_login": "test-user", "expected_host": "github.com"},
        )
        self.assertEqual((invalid_repository.status_code, invalid_branch.status_code, invalid_sha.status_code), (422, 422, 422))

        updated = client.post(
            "/api/github/local/update-build",
            headers=headers,
            json={**check_body, "expected_local_sha": "a" * 40, "expected_remote_sha": "b" * 40, "expected_login": "test-user", "expected_host": "github.com"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["status"], "current")
        self.assertEqual(
            github.calls[1],
            ("update", ("C:/work/sample", "test-user/sample", "feature/ui", "a" * 40, "b" * 40, "test-user", "github.com")),
        )
        stale = client.post(
            "/api/github/local/update-build",
            headers=headers,
            json={**check_body, "expected_local_sha": "c" * 40, "expected_remote_sha": "b" * 40, "expected_login": "test-user", "expected_host": "github.com"},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"], "The build changed. Check again.")

        dot_repository = client.post(
            "/api/github/local/check-build",
            headers=headers,
            json={**check_body, "repository": "test-user/.github"},
        )
        self.assertEqual(dot_repository.status_code, 200)

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
            authenticated_client(create_app(self.service, self.workspace, terminals=terminals, coding_agents=agents))
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
        client = self.track_core_client(
            authenticated_client(create_app(self.service, self.workspace, coding_agents=agents, git_broker=broker))
        )
        headers = {"X-JSON-CODR": "1"}

        with TestClient(client.app) as anonymous:
            denied = anonymous.post(
                "/api/git-broker/grants",
                json={"project_root": str(project), "profile": "broker"},
            )
        self.assertEqual(denied.status_code, 401)
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
        client = self.track_core_client(authenticated_client(create_app(self.service, self.workspace, terminals=FakeTerminals())))

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
                self.record = None

            def create(self, shell, cwd):
                self.record = type("Record", (), {
                    "id": "terminal-1", "pid": 123, "shell": shell, "cwd": str(cwd),
                    "status": "running", "external": False, "backend": "pipe",
                })()
                return self.record

            def get(self, terminal_id):
                if self.record is None or terminal_id != self.record.id:
                    raise KeyError(terminal_id)
                return self.record

            def interrupt(self, terminal_id):
                self.interrupted.append(terminal_id)

            def close(self, terminal_id):
                self.closed.append(terminal_id)

            def close_all(self):
                pass

        project = Path(self.temporary_directory.name) / "terminal-lifecycle-project"
        project.mkdir()
        terminals = FakeTerminals()
        client = self.track_core_client(authenticated_client(create_app(self.service, self.workspace, terminals=terminals)))
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
        self.assertEqual(response.json()["content"], "Answered: hello")
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

    def test_unified_native_task_receives_previous_history_and_structured_provenance(self):
        project_root = Path(self.temporary_directory.name) / "native-history-project"
        project_root.mkdir()
        project_id = self.client.post(
            "/api/projects/resolve", json={"root": str(project_root)}
        ).json()["project_id"]
        source_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        self.workspace.append_message(source_session, ChatMessage(
            role="user", content="Repair native compatibility parser token"
        ))
        snapshot_id = self.client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": source_session,
            "title": "Native compatibility parser repair",
            "change_type": "fix",
            "keywords": ["native-parser-token"],
        }).json()["snapshot"]["id"]
        live_session = self.client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]

        response = self.client.post("/api/tasks", json={
            "schema_version": "1",
            "command_id": "native-history-command",
            "task_id": "native-history-task",
            "thread_id": "native-history-thread",
            "project_id": project_id,
            "command_type": "capability.execute",
            "payload": {
                "capability_id": "inference.generate",
                "operation": "generate",
                "project_root": str(project_root),
                "mode": "native",
                "arguments": {
                    "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                    "prompt": "Explain the native parser token repair",
                    "session_id": live_session,
                    "attachments": [],
                },
            },
        })

        self.assertEqual(response.status_code, 200, response.text)
        completed = next(
            event for event in response.json()["events"]
            if event["event_type"] == "inference.completed"
        )
        source_ref = f"previous-session:{snapshot_id}"
        self.assertIn(source_ref, self.service.last_prompt)
        self.assertEqual(
            [item["id"] for item in completed["payload"]["result"]["references"]],
            [source_ref],
        )

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
        client = self.track_core_client(authenticated_client(create_app(BrokerModelService(), self.workspace, coding_agents=agents)))
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
        self.assertIn('"command_type":"git.read"', commands[0])

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
        client = self.track_core_client(authenticated_client(create_app(
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
                        {"kind": "verify", "checks": ["unit-tests"]},
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
        client = self.track_core_client(authenticated_client(create_app(
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
                self.prompts = []

            async def list_models(self):
                return [*await super().list_models(), {
                    "name": "deepseek-coder:6.7b-instruct", "installed": True, "size": 1,
                    "quantization": "Q4", "context_length": 4096, "capabilities": ["completion"],
                }, {
                    "name": "qwen2.5-coder:0.5b", "installed": True, "size": 1,
                    "quantization": "Q4", "context_length": 32768, "capabilities": ["completion"],
                }]

            async def supports_tools(self, model):
                return model == "qwen2.5-coder:7b-instruct-q4_K_M"

            async def tool_compatibility(self, model):
                if model == "qwen2.5-coder:0.5b":
                    return {
                        "requested_model": model,
                        "advertised_tools": False,
                        "native_tools_verified": False,
                        "route": "unavailable",
                        "effective_tool_model": None,
                        "available": False,
                    }
                return await super().tool_compatibility(model)

            async def chat(self, model, prompt, images=None):
                self.last_prompt = prompt
                self.prompts.append(prompt)
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
        skill_library = SkillLibraryService(self.workspace.data_root)
        skill_library._save([SkillPack(
            id="large-agent-context",
            name="Large agent context",
            source_format="codex",
            source_name="large-agent-context",
            skills=[SkillRecord(
                id="instructions",
                name="Large instructions",
                description="Provide project inspection guidance",
                content="capabilities: inspect\n" + ("Keep evidence grounded. " * 420),
            )],
        )])
        client = self.track_core_client(authenticated_client(create_app(model_service, self.workspace)))
        project_id = client.post(
            "/api/projects/resolve", json={"root": str(project)}
        ).json()["project_id"]
        source_session = client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        self.workspace.append_message(source_session, ChatMessage(
            role="user", content="Inspect parser history token"
        ))
        saved = client.post(f"/api/projects/{project_id}/sessions", json={
            "session_id": source_session,
            "title": "Workspace parser history",
            "change_type": "fix",
            "keywords": ["parser-history-token"],
        })
        snapshot_id = saved.json()["snapshot"]["id"]
        session_id = client.post(
            "/api/sessions", json={"project_id": project_id}
        ).json()["id"]
        session = self.workspace.get_session(session_id)
        session.selected_skill_ids = ["large-agent-context:instructions"]
        self.workspace.save_manifest(session)
        from web_app.attachments import AttachmentService
        AttachmentService(self.workspace).import_text(session.id, "workspace context evidence")
        base = {
            "project_root": str(project), "session_id": session.id,
            "engine_id": "borg", "prompt": "Inspect parser history token",
        }

        explicit = client.post("/api/workspace/tasks", json={**base, "model_selection": "qwen2.5-coder:7b-instruct-q4_K_M"})
        automatic = client.post("/api/workspace/tasks", json={**base, "model_selection": "auto"})
        multiple = client.post("/api/workspace/tasks", json={**base, "model_selection": "multi-model"})
        bad_engine = client.post("/api/workspace/tasks", json={**base, "engine_id": "missing", "model_selection": "auto"})
        bad_model = client.post("/api/workspace/tasks", json={**base, "model_selection": "opencoder:8b"})
        fallback = client.post("/api/workspace/tasks", json={**base, "model_selection": "deepseek-coder:6.7b-instruct"})
        compatibility = client.post("/api/workspace/tasks", json={**base, "model_selection": "qwen2.5-coder:0.5b"})
        missing_project = client.post("/api/workspace/tasks", json={
            **base, "project_root": str(project / "missing"), "model_selection": "auto",
        })
        other_project = Path(self.temporary_directory.name) / "other-workspace-project"
        other_project.mkdir()
        mismatched_project = client.post("/api/workspace/tasks", json={
            **base, "project_root": str(other_project), "model_selection": "auto",
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
        self.assertEqual(compatibility.status_code, 201, compatibility.text)
        self.assertEqual(compatibility.json()["effective_model"], "qwen2.5-coder:0.5b")
        self.assertEqual(compatibility.json()["route"], "json_planner_compatibility")
        self.assertTrue(any("not verified" in warning for warning in compatibility.json()["warnings"]))
        self.assertTrue(any("workspace context evidence" in prompt for prompt in model_service.prompts))
        source_ref = f"previous-session:{snapshot_id}"
        self.assertEqual(
            [item["id"] for item in explicit.json()["result"]["references"]],
            [source_ref],
        )
        self.assertEqual(
            [item["id"] for item in explicit.json()["artifact_references"]],
            [source_ref],
        )
        self.assertTrue(any(source_ref in prompt for prompt in model_service.prompts))
        self.assertEqual(missing_project.status_code, 400)
        self.assertEqual(mismatched_project.status_code, 404)

    def test_optimized_connector_catalog_and_install_plans_are_additive(self):
        client = authenticated_client(create_app(self.service, self.workspace, optimized=True))

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
        client = authenticated_client(create_app(self.service, self.workspace, optimized=True))
        session_id = client.post("/api/sessions").json()["id"]

        response = client.post(f"/api/sessions/{session_id}/hardware/openvino/install-proposal")

        self.assertEqual(response.status_code, 200)
        proposal = response.json()[0]
        self.assertIn("openvino-genai==2025.4", proposal["command"])
        self.assertIn("isolated OpenVINO runtime", proposal["explanation"])
        self.assertNotIn("driver", proposal["command"].casefold())

    def test_provider_environment_statuses_are_exposed_independently(self):
        client = authenticated_client(create_app(self.service, self.workspace, optimized=True))

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

        client = authenticated_client(create_app(BusyService(), self.workspace, hardware=FakeHardware()))

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
        self.assertEqual(reopened.json()["schema_version"], 3)

        deleted = self.client.delete(f"/api/sessions/{session_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").status_code, 404)

    def test_session_path_traversal_is_rejected(self):
        response = self.client.get("/api/sessions/not-an-id")
        self.assertEqual(response.status_code, 400)

    def test_health_reports_ollama_readiness(self):
        self.assertEqual(
            self.client.get("/api/health").json(),
                {
                    "status": "ready",
                    "app_version": APP_VERSION,
                    "revision": None,
                    "health_nonce": None,
                    "instance_id": None,
                    "started_at": None,
                    "manifest_digest": None,
                    "ollama": True,
                },
        )
        self.assertEqual(self.client.app.version, APP_VERSION)
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

        client = authenticated_client(create_app(MinimalService(), self.workspace))

        self.assertEqual(client.get("/").status_code, 200)
        response = client.post("/api/integrity-benchmarks", json={"suite": "quick", "model": "model"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("unavailable", response.json()["detail"])
        self.assertEqual(client.get("/api/integrity-benchmarks").json(), [])

    def test_hardware_detection_probe_and_cpu_restore_are_exposed(self):
        hardware = FakeHardware()
        client = authenticated_client(create_app(self.service, self.workspace, hardware=hardware))

        self.assertEqual(client.get("/api/hardware").json()["preferred_backend"], "cpu")
        self.assertEqual(client.post("/api/hardware/detect").json()[0]["id"], "cpu")
        response = client.post("/api/hardware/probe", json={"backend": "cpu", "model": "qwen2.5-coder:0.5b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hardware.probed, ("cpu", "qwen2.5-coder:0.5b"))
        self.assertEqual(client.post("/api/hardware/restore-cpu").json()["preferred_backend"], "cpu")

    def test_hardware_telemetry_combines_gpu_and_ollama_runtime_data(self):
        hardware = FakeHardware()
        client = authenticated_client(create_app(self.service, self.workspace, hardware=hardware))

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
        client = authenticated_client(create_app(self.service, self.workspace, hardware=hardware))

        response = client.post(
            "/api/hardware/probe",
            json={"backend": "ollama_gpu", "model": "qwen2.5-coder:0.5b"},
        )

        self.assertEqual(response.status_code, 200)
        profile = client.get("/api/settings").json()["gpu_optimization"]["model_profiles"]["qwen2.5-coder:0.5b"]
        self.assertEqual(profile["mode"], "gpu_preferred")

    def test_hardware_benchmark_execution_history_validation_and_busy_conflict(self):
        hardware = FakeHardware()
        client = authenticated_client(create_app(self.service, self.workspace, hardware=hardware))

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
        client = authenticated_client(create_app(self.service, self.workspace, integrity=integrity))
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

        client = authenticated_client(create_app(OfflineRosterService(), self.workspace))
        response = client.post(
            "/api/integrity-benchmarks",
            json={"suite": "quick", "model": "qwen2.5-coder:7b-instruct-q4_K_M"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(client.get("/api/integrity-benchmarks").json(), [])

    def test_integrity_benchmark_preflights_runtime_health_before_scoring(self):
        self.service.available = False

        response = self.client.post(
            "/api/integrity-benchmarks",
            json={"suite": "quick", "model": "qwen2.5-coder:7b-instruct-q4_K_M"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("runtime", response.json()["detail"].lower())
        self.assertEqual(self.client.get("/api/integrity-benchmarks").json(), [])

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
        client = authenticated_client(create_app(self.service, self.workspace, optimized=True))
        compatibility = client.get("/api/hardware/model-compatibility")
        self.assertEqual(compatibility.status_code, 200)
        cpu = next(item for item in compatibility.json() if item["backend"] == "cpu")
        self.assertTrue(any(model["model"] == "qwen2.5-coder:7b-instruct-q4_K_M" for model in cpu["models"]))
        search = client.get("/api/inference/models/search", params={"provider":"openvino", "q":"Qwen", "limit":5})
        self.assertEqual(search.status_code, 200)
        self.assertLessEqual(len(search.json()), 5)

    def test_approved_optimized_model_install_requires_confirmation_and_registers_local_path(self):
        model_id = "openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov"
        target = self.workspace.data_root / "models" / "qwen-openvino"
        target.mkdir(parents=True)

        denied = self.client.post("/api/inference/models/install", json={"model_id": model_id})
        self.assertEqual(denied.status_code, 409)
        unknown = self.client.post(
            "/api/inference/models/install",
            json={"model_id": "openvino/unapproved/model", "confirmed": True},
        )
        self.assertEqual(unknown.status_code, 404)

        with patch("web_app.inference.environments.EnvironmentManager.install_model", return_value=target):
            installed = self.client.post(
                "/api/inference/models/install",
                json={"model_id": model_id, "confirmed": True},
            )

        self.assertEqual(installed.status_code, 200)
        self.assertTrue(installed.json()["installed"])
        self.assertEqual(installed.json()["path"], str(target))
        self.assertEqual(installed.json()["provider"], "openvino")

    def test_optimized_model_receipt_failure_revokes_in_memory_trust(self):
        model_id = "openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov"
        target = self.workspace.data_root / "models" / "qwen-openvino"
        target.mkdir(parents=True)
        client = authenticated_client(create_app(self.service, self.workspace, optimized=True))
        router = client.app.state.model_runs.inference

        async def successful_probe(requested_model_id):
            router.verified_models.add(requested_model_id)
            return ProbeResult(
                model_id=requested_model_id,
                provider=ProviderKind.openvino,
                success=True,
            )

        with (
            patch("web_app.inference.environments.EnvironmentManager.install_model", return_value=target),
            patch.object(router, "probe", side_effect=successful_probe),
            patch(
                "web_app.inference.environments.EnvironmentManager.mark_verified",
                side_effect=OSError("receipt write failed"),
            ),
        ):
            response = client.post(
                "/api/inference/models/install",
                json={"model_id": model_id, "confirmed": True},
            )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(model_id, router.verified_models)
        self.assertIn(model_id, router.quarantined)

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

    def test_model_metadata_reads_real_context_and_verified_capabilities(self):
        class MetadataClient:
            async def show(self, model):
                return {
                    "capabilities": ["completion", "tools", "vision"],
                    "model_info": {"qwen3.context_length": 262144},
                }

        metadata = asyncio.run(OllamaService(client=MetadataClient()).model_metadata("qwen3.5:9b"))

        self.assertEqual(metadata, {
            "context_length": 262144,
            "tool_calling": True,
            "vision": True,
        })

    def test_tool_compatibility_distinguishes_advertised_native_and_delegated(self):
        class CapabilityClient:
            async def show(self, model):
                return {"capabilities": ["completion", "tools"]}

        service = OllamaService(client=CapabilityClient())
        service.config["tool_fallback_model"] = "qwen3:4b"

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
            "route": "broker_verified",
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

    def test_chat_auto_selects_the_configured_installed_model(self):
        self.service.config["model"] = "qwen2.5-coder:7b-instruct-q4_K_M"

        response = self.client.post(
            "/api/chat",
            json={"model": "auto", "prompt": "Hello"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "qwen2.5-coder:7b-instruct-q4_K_M")

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

        client = self.track_core_client(authenticated_client(create_app(PlannerService(), self.workspace)))
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
        self.client = self.track_core_client(authenticated_client(create_app(self.service, self.workspace)))
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


class OllamaCompatibilityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        policy = root / "model-compatibility.json"
        policy.write_text(json.dumps({
            "schema_version": 1,
            "base_fallback_order": ["base-coder:1b"],
            "models": {
                "rnj-1:8b": {
                    "alternates": ["compatible-rnj:8b"],
                    "prefer_alternate": True,
                    "reason": "Use reviewed compatible artifact.",
                },
            },
        }), encoding="utf-8")
        from web_app.model_compatibility import ModelCompatibilityLayer
        self.compatibility = ModelCompatibilityLayer.load(policy, root / "state.json")

    async def test_explicit_colon_qualified_model_is_never_fuzzy_remapped(self):
        service = OllamaService(client=object())

        self.assertEqual(service._resolve("coder:0.5b"), "coder:0.5b")

    async def test_unconfigured_exact_model_is_discovered_and_base_mode_recovers_response(self):
        class CompatibilityClient:
            def __init__(self):
                self.requests = []

            async def list(self):
                return {"models": [
                    {"name": "new-coder:latest", "digest": "sha256:" + "1" * 64, "details": {}},
                    {"name": "base-coder:1b", "digest": "sha256:" + "2" * 64, "details": {}},
                ]}

            async def chat(self, **request):
                self.requests.append(request)
                if "format" in request:
                    raise RuntimeError("model does not support format")
                return {"message": {"content": "plain compatible answer"}}

        client = CompatibilityClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        models = await service.list_models()
        result = await service.chat("new-coder:latest", "hello")

        discovered = next(item for item in models if item["name"] == "new-coder:latest")
        self.assertFalse(discovered["configured"])
        self.assertEqual(["format" in item for item in client.requests], [True, False])
        self.assertEqual(result.model, "new-coder:latest")
        self.assertEqual(result.content, "plain compatible answer")
        self.assertEqual(result.provider_events[0]["type"], "compatibility_base_mode")
        refreshed = await service.list_models()
        self.assertTrue(next(item for item in refreshed if item["name"] == "new-coder:latest")["runnable"])

    async def test_transient_cold_runner_reset_retries_same_model_before_fallback(self):
        class ColdRunnerClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [
                    {"name": "new-coder:latest", "digest": "sha256:" + "c" * 64, "details": {}},
                    {"name": "base-coder:1b", "digest": "sha256:" + "d" * 64, "details": {}},
                ]}

            async def chat(self, **request):
                self.calls.append(request["model"])
                if len(self.calls) == 1:
                    raise RuntimeError("connection was forcibly closed by the remote host")
                return {"message": {"content": json.dumps({
                    "status": "success", "summary": "Recovered", "content": "same model answer"
                })}}

        client = ColdRunnerClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        with patch("web_app.ollama_service.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await service.chat("new-coder:latest", "hello")

        self.assertEqual(client.calls, ["new-coder:latest", "new-coder:latest"])
        sleep.assert_awaited_once_with(0.5)
        self.assertEqual(result.requested_model, "new-coder:latest")
        self.assertEqual(result.effective_model, "new-coder:latest")
        self.assertEqual(result.content, "same model answer")

    async def test_digest_drift_during_inference_does_not_persist_compatibility_evidence(self):
        class DriftingClient:
            def __init__(self):
                self.list_calls = 0

            async def list(self):
                self.list_calls += 1
                digest_character = "a" if self.list_calls == 1 else "b"
                return {"models": [{
                    "name": "new-coder:latest",
                    "digest": "sha256:" + digest_character * 64,
                }]}

            async def chat(self, **_request):
                return {"message": {"content": json.dumps({
                    "status": "success",
                    "summary": "Completed",
                    "content": "answer",
                })}}

        client = DriftingClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        result = await service.chat("new-coder:latest", "hello")

        self.assertEqual(client.list_calls, 2)
        self.assertFalse(self.compatibility.state_path.exists())
        self.assertTrue(any(
            event.get("type") == "compatibility_evidence_skipped"
            and event.get("reason") == "model_digest_changed_or_unavailable"
            for event in result.provider_events
        ))

    async def test_digest_drift_during_failure_does_not_quarantine_stale_artifact(self):
        class DriftingFailureClient:
            def __init__(self):
                self.list_calls = 0

            async def list(self):
                self.list_calls += 1
                digest_character = "c" if self.list_calls == 1 else "d"
                return {"models": [{
                    "name": "new-coder:latest",
                    "digest": "sha256:" + digest_character * 64,
                }]}

            async def chat(self, **_request):
                raise RuntimeError("GGML_ASSERT failed to load model")

        client = DriftingFailureClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        with self.assertRaises(OllamaUnavailableError):
            await service.chat("new-coder:latest", "hello")

        self.assertEqual(client.list_calls, 2)
        self.assertFalse(self.compatibility.state_path.exists())

    async def test_loader_failure_quarantines_requested_digest_and_uses_reviewed_baseline(self):
        class FallbackClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [
                    {"name": "rnj-1:8b", "digest": "sha256:" + "3" * 64, "details": {}},
                    {"name": "base-coder:1b", "digest": "sha256:" + "4" * 64, "details": {}},
                ]}

            async def chat(self, **request):
                self.calls.append(request["model"])
                if request["model"] == "rnj-1:8b":
                    raise RuntimeError("GGML_ASSERT(hparams.is_swa_any()) failed")
                return {"message": {"content": json.dumps({
                    "status": "success", "summary": "Recovered", "content": "baseline answer"
                })}}

        client = FallbackClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        result = await service.chat("rnj-1:8b", "hello")

        self.assertEqual(client.calls, ["rnj-1:8b", "base-coder:1b"])
        self.assertEqual(result.model, "base-coder:1b")
        self.assertEqual(result.requested_model, "rnj-1:8b")
        self.assertEqual(result.effective_model, "base-coder:1b")
        self.assertIn("GGML_ASSERT", result.fallback_reason)
        self.assertEqual(result.content, "baseline answer")
        fallback = result.provider_events[0]
        self.assertEqual(fallback["type"], "model_fallback")
        self.assertEqual(fallback["requested_model"], "rnj-1:8b")
        self.assertEqual(fallback["effective_model"], "base-coder:1b")
        models = await service.list_models()
        rnj = next(item for item in models if item["name"] == "rnj-1:8b")
        self.assertFalse(rnj["runnable"])
        self.assertEqual(rnj["compatibility_status"], "quarantined")

    async def test_failed_preferred_alternate_is_preserved_when_requested_model_recovers(self):
        class AlternateFailureClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [
                    {"name": "rnj-1:8b", "digest": "sha256:" + "1" * 64},
                    {"name": "compatible-rnj:8b", "digest": "sha256:" + "2" * 64},
                ]}

            async def chat(self, **request):
                self.calls.append(request["model"])
                if request["model"] == "compatible-rnj:8b":
                    raise RuntimeError("GGML_ASSERT failed to load model")
                return {"message": {"content": json.dumps({
                    "status": "success",
                    "summary": "Recovered",
                    "content": "requested artifact answer",
                })}}

        client = AlternateFailureClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        result = await service.chat("rnj-1:8b", "hello")

        self.assertEqual(client.calls, ["compatible-rnj:8b", "rnj-1:8b"])
        self.assertEqual(result.requested_model, "rnj-1:8b")
        self.assertEqual(result.effective_model, "rnj-1:8b")
        self.assertEqual(result.provider_events[0]["type"], "model_fallback")
        self.assertEqual(result.provider_events[0]["failed_model"], "compatible-rnj:8b")
        self.assertEqual(result.provider_events[0]["effective_model"], "rnj-1:8b")
        self.assertIn("GGML_ASSERT", result.fallback_reason)

    async def test_missing_exact_model_is_not_silently_replaced_by_baseline(self):
        class MissingClient:
            def __init__(self):
                self.chat_calls = 0

            async def list(self):
                return {"models": [
                    {"name": "base-coder:1b", "digest": "sha256:" + "9" * 64, "details": {}},
                ]}

            async def chat(self, **_request):
                self.chat_calls += 1
                raise AssertionError("missing requested models must not invoke a fallback")

        client = MissingClient()
        service = OllamaService(client=client)
        service.set_compatibility_layer(self.compatibility)

        with self.assertRaisesRegex(OllamaUnavailableError, "Model is not installed"):
            await service.chat("missing-model:8b", "hello")

        self.assertEqual(client.chat_calls, 0)

    async def test_quarantined_verified_tool_fallback_is_not_routable(self):
        base_digest = "sha256:" + "7" * 64

        class ToolClient:
            async def list(self):
                return {"models": [
                    {"name": "unverified:1b", "digest": "sha256:" + "6" * 64},
                    {"name": "base-coder:1b", "digest": base_digest},
                ]}

            async def show(self, _model):
                return {"capabilities": ["tools"]}

        service = OllamaService(client=ToolClient())
        service.config["verified_tool_models"] = ["base-coder:1b"]
        service.config["tool_fallback_model"] = "base-coder:1b"
        service.set_compatibility_layer(self.compatibility)
        self.compatibility.record_failure(
            "base-coder:1b",
            base_digest,
            RuntimeError("GGML_ASSERT failed to load model"),
        )

        route = await service.tool_compatibility("unverified:1b")

        self.assertEqual(route["route"], "unavailable")
        self.assertIsNone(route["effective_tool_model"])
        self.assertFalse(route["available"])

    async def test_empty_tool_fallback_configuration_is_never_routable(self):
        class ToolClient:
            async def show(self, _model):
                return {"capabilities": ["tools"]}

        service = OllamaService(client=ToolClient())
        service.config["verified_tool_models"] = [""]
        service.config["tool_fallback_model"] = ""

        route = await service.tool_compatibility("unverified:1b")

        self.assertEqual(route["route"], "unavailable")
        self.assertIsNone(route["effective_tool_model"])
        self.assertFalse(route["available"])


if __name__ == "__main__":
    unittest.main()
