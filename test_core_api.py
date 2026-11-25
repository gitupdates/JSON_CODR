import io
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.approval import ApprovalStore
from web_app.core.api import create_core_router
from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore
from web_app.core.contracts import TaskCommand
from web_app.core.memory import MemoryStore
from web_app.models import MemorySettings
from web_app.core.policy import PolicyService
from web_app.core.project_registry import ProjectRegistry
from web_app.core.service import CoreService
from web_app.core.store import TaskStore
from web_app.core.auth import require_identity_scope
from web_app.core.identity import IdentityService
from web_app.core.http_identity import MutationAuthorizer


class RecordingAdapter:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, call, context):
        self.calls.append((call, context))
        yield AdapterEvent(event_type="task.output", payload={"text": "ok", "token": "hidden"})


class CoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.tasks = TaskStore(root / "tasks.sqlite")
        self.policy = PolicyService(root / "policy.sqlite")
        self.projects = ProjectRegistry(root / "projects.sqlite")
        self.projects.register(root, project_id="project-1")
        self.approvals = ApprovalStore(root / "approvals.sqlite")
        self.artifacts = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")
        self.memory = MemoryStore(root / "memory.sqlite")
        self.memory_settings = MemorySettings()
        self.adapter = RecordingAdapter()
        self.core = CoreService(
            self.tasks,
            self.policy,
            {"project.read": self.adapter, "component.install": self.adapter},
            approval_store=self.approvals,
            project_fingerprint=lambda _root: "sha256:" + "1" * 64,
            project_roots=self.projects,
        )
        self.identity = IdentityService(root / "identity")
        self.user = self.identity.bootstrap("production", "Administrator").user
        self.cli = self.identity.issue_credential(self.user.user_id, "cli", "test cli", ("agent.launch",))
        app = FastAPI()
        app.include_router(
            create_core_router(
                lambda: (self.core, self.tasks, self.policy),
                artifact_store=lambda: self.artifacts,
                capabilities=lambda: ({"capability_id": "project.read"},),
                memory_store=lambda: self.memory,
                memory_settings=lambda: self.memory_settings,
                mutation_authorizer=MutationAuthorizer(
                    self.identity,
                    lambda _request: ("json_codr_session", "json_codr_csrf", False),
                ),
            )
        )
        self.client = TestClient(app, headers={"Authorization": f"Bearer {self.cli.token}"})

    def tearDown(self) -> None:
        self.client.close()
        self.artifacts.close()
        self.memory.close()
        self.approvals.close()
        self.policy.close()
        self.tasks.close()
        self.projects.close()
        self.temporary.cleanup()

    def command(self, *, capability_id="project.read", operation="read", command_id="command-1", task_id="task-1"):
        return TaskCommand(
            command_id=command_id,
            task_id=task_id,
            thread_id="thread-1",
            project_id="project-1",
            command_type="capability.execute",
            payload=CapabilityCall(
                capability_id=capability_id,
                operation=operation,
                project_root=self.temporary.name,
            ).model_dump(mode="json"),
        ).model_dump(mode="json")

    def test_submission_validation_permission_and_reconnect_are_deterministic(self):
        response = self.client.post("/api/tasks", json=self.command())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(len(self.adapter.calls), 1)

        repeated = self.client.post("/api/tasks", json=self.command())
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(len(self.adapter.calls), 1)

        invalid = self.client.post("/api/tasks", json={"task_id": "bad id"})
        self.assertEqual(invalid.status_code, 422)

        permission = self.client.post(
            "/api/tasks",
            json=self.command(
                capability_id="git.push", operation="push", command_id="command-2", task_id="task-2",
            ),
        )
        self.assertEqual(permission.status_code, 202)
        self.assertEqual(permission.json()["status"], "pending")
        self.assertEqual(permission.json()["events"][-1]["event_type"], "task.permission_required")

    def test_cli_style_submission_resolves_project_root_to_the_registered_project_identity(self):
        command = self.command(command_id="cli-command", task_id="cli-task")
        command["project_id"] = "project-cli-path-hash"

        try:
            response = self.client.post("/api/tasks", json=command)
        except KeyError as error:
            self.fail(f"documented CLI project root was not registered: {error}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(self.tasks.command("cli-task").project_id, "project-1")

    def test_task_submission_uses_verified_agent_launch_principal_not_caller_header(self):
        missing = self.client.post(
            "/api/tasks",
            json=self.command(command_id="missing", task_id="missing"),
            headers={"Authorization": "", "X-JSON-CODR-Principal": "administrator"},
        )
        browser = self.identity.issue_credential(self.user.user_id, "browser_session", "browser", ("agent.launch",))
        wrong_kind = self.client.post(
            "/api/tasks",
            json=self.command(command_id="browser", task_id="browser"),
            headers={"Authorization": f"Bearer {browser.token}"},
        )
        wrong_scope = self.identity.issue_credential(self.user.user_id, "cli", "wrong", ("git.commit",))
        forbidden = self.client.post(
            "/api/tasks",
            json=self.command(command_id="scope", task_id="scope"),
            headers={"Authorization": f"Bearer {wrong_scope.token}"},
        )
        allowed = self.client.post(
            "/api/tasks",
            json=self.command(command_id="cli", task_id="cli"),
            headers={
                "Authorization": f"Bearer {self.cli.token}",
                "X-JSON-CODR-Principal": "spoofed-administrator",
            },
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong_kind.status_code, 401)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_permission_required_task_has_explicit_approval_route(self):
        command = self.command(
            capability_id="component.install", operation="install", command_id="command-install", task_id="task-install",
        )
        pending = self.client.post("/api/tasks", json=command)
        proposal_id = pending.json()["events"][-1]["payload"]["proposal_id"]

        missing = self.client.post("/api/tasks/task-install/approve", json={"scope": "project"})
        approved = self.client.post(
            "/api/tasks/task-install/approve",
            json={"scope": "project", "proposal_id": proposal_id},
        )
        replayed = self.client.post(
            "/api/tasks/task-install/approve",
            json={"scope": "project", "proposal_id": proposal_id},
        )

        self.assertEqual(pending.status_code, 202)
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "completed")
        self.assertEqual(replayed.status_code, 403)

    def test_event_replay_multiple_observers_steering_cancellation_and_threads(self):
        self.client.post("/api/tasks", json=self.command())
        replay = self.client.get("/api/tasks/task-1/events", params={"after_sequence": 1})
        self.assertTrue(all(event["sequence"] > 1 for event in replay.json()))

        with self.client.websocket_connect("/ws/tasks") as first, self.client.websocket_connect("/ws/tasks") as second:
            request = {"task_id": "task-1", "after_sequence": -1}
            first.send_json(request)
            second.send_json(request)
            self.assertEqual(first.receive_json(), second.receive_json())

        steered = self.client.post("/api/tasks/task-1/steer", json={"input": "continue"})
        self.assertEqual(steered.json()["event_type"], "task.steered")
        cancelled = self.client.post("/api/tasks/task-1/cancel")
        self.assertEqual(cancelled.json()["status"], "completed")
        threads = self.client.get("/api/projects/project-1/threads")
        self.assertEqual(threads.json()[0]["thread_id"], "thread-1")
        capabilities = self.client.get("/api/capabilities")
        self.assertEqual(capabilities.json()[0]["capability_id"], "project.read")

    def test_artifacts_must_belong_to_the_requested_task(self):
        record = self.artifacts.put(
            io.BytesIO(b"evidence"),
            ArtifactMetadata(task_id="task-1", media_type="text/plain"),
        )
        allowed = self.client.get(f"/api/tasks/task-1/artifacts/{record.artifact_id}")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.content, b"evidence")
        denied = self.client.get(f"/api/tasks/task-other/artifacts/{record.artifact_id}")
        self.assertEqual(denied.status_code, 403)

    def test_live_submission_uses_the_non_blocking_task_contract(self):
        response = self.client.post("/api/tasks/live", json=self.command())

        self.assertEqual(response.status_code, 202)
        self.assertIn(response.json()["status"], {"running", "completed"})
        task = self.client.get("/api/tasks/task-1")
        status = self.client.get("/api/tasks/task-1/status")
        result = self.client.get("/api/tasks/task-1/result")
        self.assertEqual(task.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(status.json()["task_id"], "task-1")
        self.assertIn(status.json()["status"], {"running", "completed"})
        self.assertFalse(any(
            event["event_type"].endswith(".delta") for event in result.json()["events"]
        ))

    def test_runtime_telemetry_and_heartbeat_are_read_only(self):
        self.tasks.record_telemetry("runtime.started", {"pid": 42})
        self.tasks.record_heartbeat("web", os.getpid(), "ready")

        telemetry = self.client.get("/api/runtime/telemetry")
        heartbeats = self.client.get("/api/runtime/heartbeats")

        self.assertEqual(telemetry.status_code, 200)
        self.assertEqual(telemetry.json()[0]["kind"], "runtime.started")
        self.assertEqual(heartbeats.status_code, 200)
        self.assertEqual(heartbeats.json()[0]["runtime_id"], "web")

        environment = {
            "JSON_CODR_REVISION": "a" * 40,
            "JSON_CODR_INSTANCE_ID": "active-test-instance",
            "JSON_CODR_STARTED_AT": "2026-11-24T12:00:00+00:00",
            "JSON_CODR_ARTIFACT_MANIFEST": "fallback:" + "a" * 40,
        }
        with patch.dict(os.environ, environment, clear=False):
            status = self.client.get("/api/runtime/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["local_only"])
        self.assertEqual(status.json()["health"], "healthy")
        self.assertIn("management_state", status.json())
        self.assertEqual(status.json()["management_state"], "managed")
        self.assertEqual(status.json()["current_process"]["pid"], os.getpid())
        self.assertEqual(status.json()["revision"], "a" * 40)
        self.assertEqual(status.json()["instance_id"], "active-test-instance")
        self.assertEqual(status.json()["telemetry"][0]["kind"], "runtime.started")

    def test_runtime_status_reports_the_answering_process_not_a_stale_foreign_heartbeat(self):
        self.tasks.record_heartbeat("web", 424242, "exited")
        old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        with self.tasks._transaction():
            self.tasks._connection.execute(
                "UPDATE runtime_heartbeats SET observed_at = ? WHERE runtime_id = 'web'",
                (old,),
            )
        environment = {
            "JSON_CODR_REVISION": "b" * 40,
            "JSON_CODR_INSTANCE_ID": "active-live-instance",
            "JSON_CODR_STARTED_AT": "2026-11-24T12:00:00+00:00",
            "JSON_CODR_ARTIFACT_MANIFEST": "fallback:" + "b" * 40,
        }

        with patch.dict(os.environ, environment, clear=False):
            status = self.client.get("/api/runtime/status")

        payload = status.json()
        self.assertEqual(status.status_code, 200)
        self.assertEqual(payload["health"], "healthy")
        self.assertEqual(payload["management_state"], "unmanaged")
        self.assertEqual(payload["heartbeats"], [{
            "runtime_id": "web",
            "pid": os.getpid(),
            "status": "ready",
            "stale": False,
        }])
        self.assertEqual(payload["historical_heartbeats"][0]["pid"], 424242)
        self.assertTrue(payload["historical_heartbeats"][0]["stale"])

    def test_runtime_status_degrades_when_build_identity_is_missing(self):
        identity_names = {
            "JSON_CODR_REVISION": "",
            "JSON_CODR_INSTANCE_ID": "",
            "JSON_CODR_STARTED_AT": "",
            "JSON_CODR_ARTIFACT_MANIFEST": "",
        }

        with patch.dict(os.environ, identity_names, clear=False):
            status = self.client.get("/api/runtime/status")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["health"], "degraded")
        self.assertIn("identity_state", status.json())
        self.assertEqual(status.json()["identity_state"], "incomplete")
        self.assertEqual(
            status.json()["missing_identity"],
            ["revision", "instance_id", "started_at", "manifest_digest"],
        )

    def test_runtime_status_recognizes_the_answering_process_stable_launcher_parent(self):
        environment = {
            "JSON_CODR_REVISION": "d" * 40,
            "JSON_CODR_INSTANCE_ID": "active-parented-instance",
            "JSON_CODR_STARTED_AT": "2026-11-24T12:00:00+00:00",
            "JSON_CODR_ARTIFACT_MANIFEST": "fallback:" + "d" * 40,
            "JSON_CODR_SUPERVISOR_PID": str(os.getppid()),
        }

        with patch.dict(os.environ, environment, clear=False):
            status = self.client.get("/api/runtime/status")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["management_state"], "managed")
        self.assertEqual(status.json()["management_source"], "stable-launcher")
        self.assertEqual(status.json()["supervisor_pid"], os.getppid())

    def test_privileged_scope_dependency_rejects_legacy_principal_header(self):
        identity = self.identity
        credential = identity.issue_credential(self.user.user_id, "browser_session", "test", ("lesson.edit",))
        app = FastAPI()

        @app.get("/protected")
        def protected(_principal=Depends(require_identity_scope(lambda: identity, "lesson.edit"))):
            return {"ok": True}

        with TestClient(app) as client:
            legacy = client.get("/protected", headers={"X-JSON-CODR-Principal": "Administrator"})
            allowed = client.get("/protected", headers={"Authorization": f"Bearer {credential.token}"})

        self.assertEqual(legacy.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_plan_and_step_revisions_are_editable_rejectable_and_stale_safe(self):
        self.client.post("/api/tasks", json=self.command())
        plan = {
            "schema_version": "1", "plan_id": "plan-1", "revision": 1,
            "goal_id": "goal-1", "goal_revision": 1,
            "steps": [{
                "schema_version": "1", "step_id": "step-1", "plan_id": "plan-1",
                "plan_revision": 1, "criterion_ids": ["criterion-1"],
                "capability_id": "project.read", "operation": "read", "arguments": {},
                "depends_on": [],
            }],
        }
        created = self.client.post(
            "/api/tasks/task-1/plans/plan-1/revise",
            json={"expected_revision": None, "action": "edit", "plan": plan},
        )
        approved = self.client.post(
            "/api/tasks/task-1/plans/plan-1/revise",
            json={"expected_revision": 1, "action": "approve", "plan": plan},
        )
        step = {**plan["steps"][0], "operation": "search"}
        revised = self.client.post(
            "/api/tasks/task-1/plans/plan-1/steps/step-1/revise",
            json={"expected_revision": 1, "action": "edit", "step": step},
        )
        stale = self.client.post(
            "/api/tasks/task-1/plans/plan-1/steps/step-1/revise",
            json={"expected_revision": 1, "action": "reject", "reason": "change it"},
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["revision"], 1)
        self.assertEqual(revised.json()["revision"], 2)
        self.assertEqual(revised.json()["steps"][0]["operation"], "search")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(len(self.client.get("/api/tasks/task-1/plans/plan-1").json()), 2)

    def test_collective_memory_api_scopes_search_and_revocation_to_principal(self):
        created = self.client.post(
            "/api/projects/project-1/memory",
            headers={"X-JSON-CODR-Principal": "administrator"},
            json={
                "thread_id": "thread-1",
                "task_id": "task-1",
                "kind": "verified_outcome",
                "content": "Planner contract verification passed.",
                "source_refs": ["event:verified-1"],
                "idempotency_key": "task-1:verified-1",
            },
        )
        found = self.client.get(
            "/api/projects/project-1/memory/search",
            headers={"X-JSON-CODR-Principal": "administrator"},
            params={"query": "planner"},
        )
        isolated = self.client.get(
            "/api/projects/project-1/memory/search",
            headers={"X-JSON-CODR-Principal": "other-user"},
            params={"query": "planner"},
        )
        revoked = self.client.post(
            f"/api/projects/project-1/memory/{created.json()['memory_id']}/revoke",
            headers={"X-JSON-CODR-Principal": "administrator"},
            json={"reason": "superseded evidence"},
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(found.status_code, 200)
        self.assertEqual(len(found.json()), 1)
        self.assertEqual(isolated.json(), [])
        self.assertEqual(revoked.json()["status"], "revoked")

    def test_collective_memory_api_requires_global_and_per_record_detailed_retention_opt_in(self):
        payload = {
            "thread_id": "thread-1",
            "task_id": "task-1",
            "kind": "transcript",
            "content": "RAW TRANSCRIPT:\nuser: fix it\nassistant: result",
            "source_refs": ["event:transcript-1"],
            "retain_details": True,
            "idempotency_key": "task-1:transcript-1",
        }

        blocked = self.client.post("/api/projects/project-1/memory", json=payload)
        self.memory_settings = MemorySettings(detailed_retention_enabled=True)
        allowed = self.client.post("/api/projects/project-1/memory", json=payload)

        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(allowed.status_code, 201)

    def test_collective_memory_search_distinguishes_configured_default_from_explicit_limit(self):
        self.memory_settings = MemorySettings(search_limit=2)
        headers = {"X-JSON-CODR-Principal": "administrator"}
        for index in range(5):
            created = self.client.post(
                "/api/projects/project-limit/memory",
                headers=headers,
                json={
                    "thread_id": "thread-1",
                    "task_id": f"task-{index}",
                    "kind": "verified_outcome",
                    "content": f"Verified planner outcome {index}.",
                    "source_refs": [f"event:verified-{index}"],
                    "idempotency_key": f"task-{index}:verified",
                },
            )
            self.assertEqual(created.status_code, 201)

        configured = self.client.get(
            "/api/projects/project-limit/memory/search",
            headers=headers,
            params={"query": "planner"},
        )
        explicit = self.client.get(
            "/api/projects/project-limit/memory/search",
            headers=headers,
            params={"query": "planner", "limit": 5},
        )

        self.assertEqual(len(configured.json()), 2)
        self.assertEqual(len(explicit.json()), 5)


if __name__ == "__main__":
    unittest.main()
