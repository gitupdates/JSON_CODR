import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from web_app.core.contracts import (
    CompletionCriterion,
    CriterionKind,
    CriterionStatus,
    EvidenceRef,
    GoalSpec,
    PlanRevision,
    PlannedStep,
    VerificationReport,
)


class GoalContractTests(unittest.TestCase):
    def test_goal_plan_and_verification_round_trip_without_mutable_state(self):
        criterion = CompletionCriterion(
            criterion_id="tests-pass",
            kind=CriterionKind.command_succeeds,
            description="Focused tests pass",
            parameters={"command": "python -m unittest test_store"},
        )
        goal = GoalSpec(
            goal_id="goal-1", revision=1, objective="Implement replay-safe task execution",
            criteria=(criterion,), accepted=True,
        )
        step = PlannedStep(
            step_id="step-1", plan_id="plan-1", plan_revision=1,
            criterion_ids=(criterion.criterion_id,), capability_id="test.run",
            operation="focused_tests", arguments={"command": "python -m unittest test_store"},
        )
        plan = PlanRevision(
            plan_id="plan-1", revision=1, goal_id=goal.goal_id,
            goal_revision=goal.revision, steps=(step,),
        )
        evidence = EvidenceRef(
            evidence_id="evidence-1", task_id="task-1", project_id="project-1",
            goal_id=goal.goal_id, goal_revision=goal.revision, criterion_id=criterion.criterion_id,
            source_ref="event:event-1", project_fingerprint="sha256:" + "1" * 64,
            observed_at=datetime.now(UTC),
        )
        report = VerificationReport(
            report_id="report-1", task_id="task-1", project_id="project-1",
            goal_id=goal.goal_id, goal_revision=goal.revision,
            expected_criterion_ids=(criterion.criterion_id,),
            results={criterion.criterion_id: CriterionStatus.passed},
            evidence=(evidence,), verified_at=datetime.now(UTC),
        )

        self.assertEqual(GoalSpec.model_validate_json(goal.model_dump_json()), goal)
        self.assertEqual(PlanRevision.model_validate_json(plan.model_dump_json()), plan)
        self.assertTrue(report.satisfied)
        with self.assertRaises(ValidationError):
            goal.revision = 2

    def test_verification_requires_one_result_for_every_goal_criterion(self):
        with self.assertRaises(ValidationError):
            VerificationReport(
                report_id="report-1", task_id="task-1", project_id="project-1",
                goal_id="goal-1", goal_revision=1,
                expected_criterion_ids=("one", "two"),
                results={"one": CriterionStatus.passed}, verified_at=datetime.now(UTC),
            )

    def test_passing_result_requires_fresh_matching_evidence(self):
        with self.assertRaises(ValidationError):
            VerificationReport(
                report_id="report-1", task_id="task-1", project_id="project-1",
                goal_id="goal-1", goal_revision=1, expected_criterion_ids=("one",),
                results={"one": CriterionStatus.passed}, verified_at=datetime.now(UTC),
            )


if __name__ == "__main__":
    unittest.main()
