import unittest

from pydantic import ValidationError

from web_app.core.contracts import (
    ConnectorStepMetadata,
    EffectClass,
    OriginReference,
    PlanReviewStatus,
    PlanRevision,
    PlannedStep,
    RevisionAuthor,
    StepDisposition,
    StepReviewStatus,
)


class PlanContractTests(unittest.TestCase):
    def make_step(self, step_id="step-1", **changes):
        values = {
            "step_id": step_id,
            "plan_id": "plan-1",
            "plan_revision": 1,
            "criterion_ids": ("verified",),
            "title": "Inspect project",
            "purpose": "Gather current project evidence",
            "dependencies": (),
            "capability_id": "project.read",
            "operation": "read",
            "target_path": "src/app.py",
            "arguments": {"path": "src/app.py"},
            "effect_class": EffectClass.observe,
            "expected_evidence": ("project snapshot",),
        }
        values.update(changes)
        return PlannedStep(**values)

    def make_plan(self, steps=None, **changes):
        values = {
            "plan_id": "plan-1",
            "revision": 1,
            "goal_id": "goal-1",
            "goal_revision": 1,
            "summary": "Inspect and update the project",
            "expected_deliverables": ("verified project",),
            "author": RevisionAuthor.planner,
            "revision_reason": "initial plan",
            "review_status": PlanReviewStatus.in_review,
            "steps": tuple(steps or (self.make_step(),)),
        }
        values.update(changes)
        return PlanRevision(**values)

    def test_reviewable_plan_round_trips_with_stable_digests(self):
        origin = OriginReference(
            origin_type="skill", origin_id="review-code",
            content_digest="sha256:" + "1" * 64,
        )
        connector = ConnectorStepMetadata(
            server_id="issues", tool_name="list_issues",
            tool_schema_digest="sha256:" + "2" * 64,
            argument_digest="sha256:" + "3" * 64,
            declared_annotations={"readOnlyHint": True},
            requested_scope_refs=("issues:read",),
            data_origin="Issue tracker",
        )
        plan = self.make_plan(steps=(self.make_step(origins=(origin,), connector=connector),))

        restored = PlanRevision.model_validate_json(plan.model_dump_json())

        self.assertEqual(restored, plan)
        self.assertRegex(plan.canonical_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(plan.steps[0].canonical_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(restored.canonical_digest, plan.canonical_digest)
        self.assertEqual(restored.steps[0].canonical_digest, plan.steps[0].canonical_digest)

    def test_step_digest_changes_when_reviewed_arguments_change(self):
        first = self.make_step(arguments={"path": "src/app.py"})
        changed = self.make_step(arguments={"path": "src/settings.py"})

        self.assertNotEqual(first.canonical_digest, changed.canonical_digest)

    def test_content_digest_does_not_change_with_review_or_execution_state(self):
        pending = self.make_step()
        completed = self.make_step(
            review_status=StepReviewStatus.approved,
            disposition=StepDisposition.completed,
        )
        review_plan = self.make_plan(steps=(pending,))
        approved_plan = self.make_plan(
            steps=(completed,), review_status=PlanReviewStatus.approved,
        )

        self.assertEqual(pending.canonical_digest, completed.canonical_digest)
        self.assertEqual(review_plan.canonical_digest, approved_plan.canonical_digest)

    def test_supplied_incorrect_digest_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "canonical digest"):
            self.make_step(canonical_digest="sha256:" + "f" * 64)

    def test_plan_rejects_missing_and_cyclic_dependencies(self):
        missing = self.make_step(dependencies=("step-missing",))
        with self.assertRaisesRegex(ValidationError, "missing step"):
            self.make_plan(steps=(missing,))

        first = self.make_step("step-1", dependencies=("step-2",))
        second = self.make_step("step-2", dependencies=("step-1",))
        with self.assertRaisesRegex(ValidationError, "cycle"):
            self.make_plan(steps=(first, second))

    def test_connector_metadata_rejects_secret_material(self):
        with self.assertRaises(ValidationError):
            ConnectorStepMetadata(
                server_id="issues", tool_name="list_issues",
                tool_schema_digest="sha256:" + "2" * 64,
                argument_digest="sha256:" + "3" * 64,
                access_token="do-not-store",
            )

    def test_review_and_completion_state_are_explicit(self):
        step = self.make_step(
            review_status=StepReviewStatus.approved,
            disposition=StepDisposition.completed,
        )
        plan = self.make_plan(steps=(step,), review_status=PlanReviewStatus.approved)

        self.assertEqual(plan.review_status, PlanReviewStatus.approved)
        self.assertEqual(plan.steps[0].disposition, StepDisposition.completed)
        with self.assertRaises(ValidationError):
            plan.revision = 2


if __name__ == "__main__":
    unittest.main()
