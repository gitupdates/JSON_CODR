import io
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.api import create_core_router
from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore
from web_app.core.contracts import TaskCommand
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
        self.artifacts = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")
        self.adapter = RecordingAdapter()
        self.core = CoreService(self.tasks, self.policy, {"project.read": self.adapter})
        app = FastAPI()
        app.include_router(
            create_core_router(
                lambda: (self.core, self.tasks, self.policy),
                artifact_store=lambda: self.artifacts,
                capabilities=lambda: ({"capability_id": "project.read"},),
            )
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.artifacts.close()
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

        approved = self.client.post("/api/tasks/task-install/approve", json={"scope": "project"})

        self.assertEqual(pending.status_code, 202)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "completed")

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


if __name__ == "__main__":
    unittest.main()
