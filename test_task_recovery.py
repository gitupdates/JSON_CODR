import tempfile
import unittest
from pathlib import Path

from web_app.core.capabilities import CapabilityRegistry
from web_app.core.contracts import (
    CapabilityManifest, ManifestAuthority, ModelScope, PlanRevision, PlannedStep,
    TaskCommand, TaskEventDraft,
)
from web_app.core.plan_service import PlanConflict, PlanService
from web_app.core.project_adapter import ProjectAdapter
from web_app.core.store import TaskStore


class TaskRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "file.txt").write_text("one", encoding="utf-8")
        self.adapter = ProjectAdapter(self.root / "state")
        self.store = TaskStore(self.root / "tasks.sqlite")
        self.store.create(TaskCommand(
            command_id="command-1", task_id="task-1", thread_id="thread-1",
            project_id="project-1", command_type="agent.run", payload={},
        ))
        registry = CapabilityRegistry()
        registry.register(CapabilityManifest(
            capability_id="project.read", implementation_id="project.read.builtin", version="1",
            model_scope=ModelScope.independent, authority=ManifestAuthority.host_builtin,
            manifest_digest="sha256:" + "a" * 64,
        ), lambda: object(), lambda _: True)
        self.service = PlanService(self.store, registry)
        self.plan = self.service.create("task-1", PlanRevision(
            plan_id="plan-1", revision=1, goal_id="goal-1", goal_revision=1,
            steps=(PlannedStep(
                step_id="step-1", plan_id="plan-1", plan_revision=1,
                criterion_ids=("verified",), capability_id="project.read", operation="read",
            ),),
        ))
        snapshot = self.adapter.snapshot(self.project)
        self.store.append("task-1", TaskEventDraft(
            event_type="agent.plan_context_bound", payload={
                "plan_id": "plan-1", "plan_revision": 1,
                "project_fingerprint": snapshot.fingerprint,
                "policy_digest": "sha256:" + "1" * 64,
            },
        ))
        self.store.append("task-1", TaskEventDraft(
            event_type="agent.phase_changed", payload={"phase": "plan_review"},
        ))

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_policy_apply_creates_new_revision_and_invalidates_pending_approval(self):
        self.service.approve_plan("task-1", "plan-1", 1, "user", self.plan.canonical_digest)

        revised = self.service.apply_policy(
            "task-1", "plan-1", 1, self.plan.canonical_digest,
            policy_digest="sha256:" + "2" * 64,
        )

        self.assertEqual(revised.revision, 2)
        self.assertEqual(self.store.plan_decisions("task-1", "plan-1", 2), ())
        binding = next(event for event in reversed(self.store.events("task-1")) if event.event_type == "agent.plan_context_bound")
        self.assertEqual(binding.payload["policy_digest"], "sha256:" + "2" * 64)

    def test_baseline_refresh_uses_canonical_project_snapshot(self):
        (self.project / "file.txt").write_text("two", encoding="utf-8")
        expected = self.adapter.snapshot(self.project)

        revised = self.service.refresh_baseline(
            "task-1", "plan-1", 1, self.plan.canonical_digest,
            project_adapter=self.adapter, project_root=self.project,
        )

        self.assertEqual(revised.revision, 2)
        event = next(event for event in reversed(self.store.events("task-1")) if event.event_type == "agent.baseline_refreshed")
        self.assertEqual(event.payload["project_fingerprint"], expected.fingerprint)

    def test_recovery_rejects_running_task_and_missing_ancestry(self):
        self.store.append("task-1", TaskEventDraft(
            event_type="agent.phase_changed", payload={"phase": "executing"},
        ))
        with self.assertRaises(PlanConflict):
            self.service.apply_policy(
                "task-1", "plan-1", 1, self.plan.canonical_digest,
                policy_digest="sha256:" + "2" * 64,
            )

        self.store.create(TaskCommand(
            command_id="command-2", task_id="task-2", thread_id="thread-1",
            project_id="project-1", command_type="agent.run", payload={},
        ))
        other = self.service.create("task-2", PlanRevision(
            plan_id="plan-2", revision=1, goal_id="goal-1", goal_revision=1,
            steps=(PlannedStep(
                step_id="step-1", plan_id="plan-2", plan_revision=1,
                criterion_ids=("verified",), capability_id="project.read", operation="read",
            ),),
        ))
        with self.assertRaises(PlanConflict):
            self.service.apply_policy(
                "task-2", "plan-2", 1, other.canonical_digest,
                policy_digest="sha256:" + "2" * 64,
            )


if __name__ == "__main__":
    unittest.main()
