import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_app.core.api import create_core_router
from web_app.core.capabilities import CapabilityRegistry
from web_app.core.contracts import (
    CapabilityManifest, ManifestAuthority, ModelScope, PlanRevision, PlannedStep, TaskCommand,
)
from web_app.core.plan_service import PlanService
from web_app.core.policy import PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class PlanApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.tasks = TaskStore(root / "tasks.sqlite")
        self.policy = PolicyService(root / "policy.sqlite")
        self.core = CoreService(self.tasks, self.policy, {})
        registry = CapabilityRegistry()
        registry.register(CapabilityManifest(
            capability_id="project.read", implementation_id="project.read.builtin", version="1",
            model_scope=ModelScope.independent, authority=ManifestAuthority.host_builtin,
            manifest_digest="sha256:" + "a" * 64,
        ), lambda: object(), lambda _: True)
        self.plans = PlanService(self.tasks, registry)
        self.tasks.create(TaskCommand(
            command_id="command-1", task_id="task-1", thread_id="thread-1",
            project_id="project-1", command_type="agent.run", payload={},
        ))
        self.plan = self.plans.create("task-1", PlanRevision(
            plan_id="plan-1", revision=1, goal_id="goal-1", goal_revision=1,
            steps=(PlannedStep(
                step_id="step-1", plan_id="plan-1", plan_revision=1,
                criterion_ids=("verified",), capability_id="project.read", operation="read",
            ),),
        ))
        app = FastAPI()
        app.include_router(create_core_router(
            lambda: (self.core, self.tasks, self.policy), plan_service=lambda: self.plans,
        ))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.policy.close()
        self.tasks.close()
        self.temporary.cleanup()

    def test_plan_and_step_review_routes_require_expected_digest(self):
        listed = self.client.get("/api/tasks/task-1/plans")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["canonical_digest"], self.plan.canonical_digest)

        approved = self.client.post("/api/tasks/task-1/plans/plan-1/1/approve", json={
            "expected_plan_digest": self.plan.canonical_digest,
        })
        step = self.client.post("/api/tasks/task-1/plans/plan-1/1/steps/step-1/approve", json={
            "expected_plan_digest": self.plan.canonical_digest,
        })
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(step.status_code, 200)

        stale = self.client.post("/api/tasks/task-1/plans/plan-1/1/reject", json={
            "expected_plan_digest": "sha256:" + "f" * 64, "reason": "wrong",
        })
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["current_digest"], self.plan.canonical_digest)

    def test_edit_and_revise_create_new_revisions(self):
        edited = self.client.patch("/api/tasks/task-1/plans/plan-1/1/steps/step-1", json={
            "expected_plan_digest": self.plan.canonical_digest,
            "changes": {"title": "Inspect configuration"},
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["revision"], 2)

        revised = self.client.post("/api/tasks/task-1/plans/plan-1/2/revise", json={
            "expected_plan_digest": edited.json()["canonical_digest"],
            "summary": "Updated plan", "reason": "requested changes",
        })
        self.assertEqual(revised.status_code, 200)
        self.assertEqual(revised.json()["revision"], 3)

    def test_missing_plan_and_invalid_edit_use_problem_details(self):
        missing = self.client.post("/api/tasks/task-1/plans/missing/1/approve", json={
            "expected_plan_digest": self.plan.canonical_digest,
        })
        invalid = self.client.patch("/api/tasks/task-1/plans/plan-1/1/steps/step-1", json={
            "expected_plan_digest": self.plan.canonical_digest,
            "changes": {"effect_class": "destructive"},
        })
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["status"], 404)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["detail"]["status"], 422)


if __name__ == "__main__":
    unittest.main()
