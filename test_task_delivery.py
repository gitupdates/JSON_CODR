import io
import tempfile
import unittest
from pathlib import Path

from web_app.core.agent_verification import build_task_delivery
from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore
from web_app.core.contracts import (
    PlanRevision, PlannedStep, TaskCommand, TaskEventDraft,
)
from web_app.core.store import TaskStore


class TaskDeliveryTests(unittest.TestCase):
    def test_delivery_is_derived_from_durable_events_and_authorized_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = TaskStore(root / "tasks.sqlite")
            artifacts = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")
            try:
                tasks.create(TaskCommand(
                    command_id="command-1", task_id="task-1", thread_id="thread-1",
                    project_id="project-1", command_type="agent.run", payload={},
                ))
                plan = PlanRevision(
                    plan_id="plan-1", revision=1, goal_id="goal-1", goal_revision=1,
                    steps=(PlannedStep(
                        step_id="step-1", plan_id="plan-1", plan_revision=1,
                        criterion_ids=("verified",), capability_id="project.read", operation="read",
                    ),),
                )
                tasks.append_plan("task-1", plan)
                tasks.append("task-1", TaskEventDraft(
                    event_type="agent.plan_context_bound", payload={
                        "plan_id": "plan-1", "plan_revision": 1,
                        "project_fingerprint": "sha256:" + "1" * 64,
                        "policy_digest": "sha256:" + "2" * 64,
                    },
                ))
                tasks.append("task-1", TaskEventDraft(
                    event_type="agent.action_completed", payload={
                        "step_id": "step-1", "step_digest": plan.steps[0].canonical_digest,
                        "child_task_id": "child-1", "changed_paths": ["src/app.py"],
                    },
                ))
                tasks.append("task-1", TaskEventDraft(
                    event_type="agent.verification_completed", payload={
                        "report_id": "report-1", "results": {"verified": "passed"},
                        "evidence": [{"evidence_id": "evidence-1"}],
                    },
                ))
                artifact = artifacts.put(io.BytesIO(b"report"), ArtifactMetadata(
                    task_id="task-1", media_type="text/plain",
                    metadata={"path": "C:/secret/project/report.txt", "token": "hidden"},
                ))

                delivery = build_task_delivery("task-1", tasks, artifacts)

                self.assertEqual(delivery.executed_plan_revision, 1)
                self.assertEqual(delivery.changed_paths, ("src/app.py",))
                self.assertEqual(delivery.verification["report_id"], "report-1")
                self.assertEqual(delivery.artifacts[0]["artifact_id"], artifact.artifact_id)
                self.assertEqual(delivery.artifacts[0]["download_url"], f"/api/tasks/task-1/artifacts/{artifact.artifact_id}")
                self.assertNotIn("C:/secret", delivery.model_dump_json())
                self.assertNotIn("hidden", delivery.model_dump_json())
            finally:
                artifacts.close()
                tasks.close()

    def test_missing_verification_is_disclosed_as_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = TaskStore(root / "tasks.sqlite")
            artifacts = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")
            try:
                tasks.create(TaskCommand(
                    command_id="command-1", task_id="task-1", thread_id="thread-1",
                    project_id="project-1", command_type="agent.run", payload={},
                ))
                delivery = build_task_delivery("task-1", tasks, artifacts)
                self.assertIn("Verification has not completed", delivery.warnings)
            finally:
                artifacts.close()
                tasks.close()


if __name__ == "__main__":
    unittest.main()
