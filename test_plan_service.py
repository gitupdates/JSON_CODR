import tempfile
import unittest
from pathlib import Path

from web_app.core.capabilities import CapabilityRegistry
from web_app.core.contracts import (
    CapabilityManifest,
    EffectClass,
    ManifestAuthority,
    ModelScope,
    PlanRevision,
    PlannedStep,
    StepReviewStatus,
    TaskCommand,
)
from web_app.core.plan_service import PlanConflict, PlanService
from web_app.core.store import TaskStore


def manifest(capability_id: str) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id=capability_id,
        implementation_id=f"{capability_id}.builtin",
        version="1",
        model_scope=ModelScope.independent,
        authority=ManifestAuthority.host_builtin,
        manifest_digest="sha256:" + "a" * 64,
    )


def revision(number=1, parent=None) -> PlanRevision:
    def step(step_id, dependencies=(), target=None):
        return PlannedStep(
            step_id=step_id, plan_id="plan-1", plan_revision=number,
            criterion_ids=("verified",), title=step_id, dependencies=dependencies,
            capability_id="project.read", operation="read", target_path=target,
            arguments={"path": target or step_id}, effect_class=EffectClass.observe,
        )
    return PlanRevision(
        plan_id="plan-1", revision=number, parent_revision=parent,
        goal_id="goal-1", goal_revision=1, summary="Review the project",
        steps=(step("step-a", target="a.py"), step("step-b", ("step-a",), "b.py"), step("step-c", target="c.py")),
    )


class PlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temporary.name) / "tasks.sqlite")
        self.store.create(TaskCommand(
            command_id="command-1", task_id="task-1", thread_id="thread-1",
            project_id="project-1", command_type="agent.run", payload={},
        ))
        self.registry = CapabilityRegistry()
        self.registry.register(manifest("project.read"), lambda: object(), lambda _: True)
        self.service = PlanService(self.store, self.registry)
        self.current = self.service.create("task-1", revision())

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_whole_plan_and_step_decisions_require_exact_digest(self):
        step = self.service.approve_step(
            "task-1", "plan-1", 1, "step-a", "user", self.current.canonical_digest,
        )
        plan = self.service.approve_plan(
            "task-1", "plan-1", 1, "user", self.current.canonical_digest,
        )
        self.assertEqual(step.step_id, "step-a")
        self.assertIsNone(plan.step_id)

        with self.assertRaises(PlanConflict) as caught:
            self.service.reject_step(
                "task-1", "plan-1", 1, "step-b", "user", "sha256:" + "f" * 64, "wrong",
            )
        self.assertEqual(caught.exception.current_digest, self.current.canonical_digest)
        self.assertEqual(caught.exception.current_revision, 1)

    def test_edit_creates_revision_and_invalidates_transitive_dependents_only(self):
        self.service.approve_step("task-1", "plan-1", 1, "step-a", "user", self.current.canonical_digest)
        self.service.approve_step("task-1", "plan-1", 1, "step-b", "user", self.current.canonical_digest)
        self.service.approve_step("task-1", "plan-1", 1, "step-c", "user", self.current.canonical_digest)

        edited = self.service.edit_step(
            "task-1", "plan-1", 1, "step-a", "user", self.current.canonical_digest,
            {"target_path": "src/new.py", "arguments": {"path": "src/new.py"}},
        )

        self.assertEqual(edited.revision, 2)
        statuses = {step.step_id: step.review_status for step in edited.steps}
        self.assertEqual(statuses["step-a"], StepReviewStatus.pending)
        self.assertEqual(statuses["step-b"], StepReviewStatus.pending)
        self.assertEqual(statuses["step-c"], StepReviewStatus.approved)
        self.assertEqual(edited.steps[0].effect_class, EffectClass.observe)

    def test_rejection_can_only_recover_through_new_revision(self):
        self.service.reject_plan(
            "task-1", "plan-1", 1, "user", self.current.canonical_digest, "revise it",
        )
        with self.assertRaises(PlanConflict):
            self.service.approve_plan("task-1", "plan-1", 1, "user", self.current.canonical_digest)

        newer = self.service.revise_plan(
            "task-1", "plan-1", 1, "user", self.current.canonical_digest,
            summary="Revised plan", reason="Address review",
        )
        approved = self.service.approve_plan(
            "task-1", "plan-1", 2, "user", newer.canonical_digest,
        )
        self.assertEqual(approved.plan_revision, 2)

    def test_edits_are_bounded_and_capabilities_are_validated(self):
        with self.assertRaisesRegex(ValueError, "editable"):
            self.service.edit_step(
                "task-1", "plan-1", 1, "step-a", "user", self.current.canonical_digest,
                {"effect_class": "destructive"},
            )
        with self.assertRaisesRegex(ValueError, "unknown capability"):
            self.service.edit_step(
                "task-1", "plan-1", 1, "step-a", "user", self.current.canonical_digest,
                {"capability_id": "missing.tool"},
            )
        with self.assertRaisesRegex(ValueError, "one capability call"):
            self.service.edit_step(
                "task-1", "plan-1", 1, "step-a", "user", self.current.canonical_digest,
                {"calls": [{"operation": "read"}, {"operation": "write"}]},
            )


if __name__ == "__main__":
    unittest.main()
