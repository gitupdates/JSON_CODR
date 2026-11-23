import io
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.approval import ApprovalStore
from web_app.core.api import create_core_router
from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore
from web_app.core.contracts import TaskCommand
from web_app.core.memory import MemoryStore
from web_app.models import MemorySettings
from web_app.core.policy import PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


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
        self.approvals = ApprovalStore(root / "approvals.sqlite")
        self.artifacts = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")
        self.memory = MemoryStore(root / "memory.sqlite")
        self.memory_settings = MemorySettings()
        self.adapter = RecordingAdapter()
        self.core = CoreService(
            self.tasks,
            self.policy,
            {"project.read": self.adapter},
            approval_store=self.approvals,
            project_fingerprint=lambda _root: "sha256:" + "1" * 64,
        )
        app = FastAPI()
        app.include_router(
            create_core_router(
                lambda: (self.core, self.tasks, self.policy),
                artifact_store=lambda: self.artifacts,
                capabilities=lambda: ({"capability_id": "project.read"},),
                memory_store=lambda: self.memory,
                memory_settings=lambda: self.memory_settings,
            )
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.artifacts.close()
        self.memory.close()
        self.approvals.close()
        self.policy.close()
        self.tasks.close()
        self.temporary.cleanup()

    def command(self, *, operation="read", command_id="command-1", task_id="task-1"):
        return TaskCommand(
            command_id=command_id,
            task_id=task_id,
            thread_id="thread-1",
            project_id="project-1",
            command_type="capability.execute",
            payload=CapabilityCall(
                capability_id="project.read",
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
            json=self.command(operation="push", command_id="command-2", task_id="task-2"),
        )
        self.assertEqual(permission.status_code, 202)
        self.assertEqual(permission.json()["status"], "pending")
        self.assertEqual(permission.json()["events"][-1]["event_type"], "task.permission_required")

    def test_permission_required_task_has_explicit_approval_route(self):
        command = self.command(operation="install", command_id="command-install", task_id="task-install")
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
        self.assertEqual(task.status_code, 200)

    def test_runtime_telemetry_and_heartbeat_are_read_only(self):
        self.tasks.record_telemetry("runtime.started", {"pid": 42})
        self.tasks.record_heartbeat("web", 42, "ready")

        telemetry = self.client.get("/api/runtime/telemetry")
        heartbeats = self.client.get("/api/runtime/heartbeats")

        self.assertEqual(telemetry.status_code, 200)
        self.assertEqual(telemetry.json()[0]["kind"], "runtime.started")
        self.assertEqual(heartbeats.status_code, 200)
        self.assertEqual(heartbeats.json()[0]["runtime_id"], "web")

        status = self.client.get("/api/runtime/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["local_only"])
        self.assertEqual(status.json()["health"], "healthy")
        self.assertEqual(status.json()["telemetry"][0]["kind"], "runtime.started")

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
