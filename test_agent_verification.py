import unittest
from datetime import UTC, datetime

from web_app.core.agent_verification import (
    EvidenceResolver,
    FailureNormalizer,
    RepairLoopGuard,
    StaleEvidence,
)
from web_app.core.contracts import (
    CompletionCriterion,
    CriterionKind,
    CriterionStatus,
    EvidenceRef,
    GoalSpec,
    TaskCommand,
    TaskEventDraft,
    VerificationReport,
)


class AgentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.goal = GoalSpec(
            goal_id="goal-1", revision=2, objective="Repair the project",
            criteria=(CompletionCriterion(
                criterion_id="tests", kind=CriterionKind.command_succeeds,
                description="Tests pass",
            ),), accepted=True,
        )
        self.command = TaskCommand(
            command_id="command-1", task_id="task-1", thread_id="thread-1",
            project_id="project-1", command_type="agent.run",
        )

    def report(self, fingerprint="sha256:" + "1" * 64):
        evidence = EvidenceRef(
            evidence_id="evidence-1", task_id="task-1", project_id="project-1",
            goal_id="goal-1", goal_revision=2, criterion_id="tests",
            source_ref="event:event-1", project_fingerprint=fingerprint,
            observed_at=datetime.now(UTC),
        )
        return VerificationReport(
            report_id="report-1", task_id="task-1", project_id="project-1",
            goal_id="goal-1", goal_revision=2, expected_criterion_ids=("tests",),
            results={"tests": CriterionStatus.passed}, evidence=(evidence,),
            verified_at=datetime.now(UTC),
        )

    def test_evidence_resolver_rejects_stale_project_state(self):
        with self.assertRaises(StaleEvidence):
            EvidenceResolver().validate(
                self.report(), self.goal, self.command,
                current_project_fingerprint="sha256:" + "2" * 64,
            )

    def test_evidence_resolver_accepts_matching_current_state(self):
        resolved = EvidenceResolver().validate(
            self.report(), self.goal, self.command,
            current_project_fingerprint="sha256:" + "1" * 64,
        )
        self.assertTrue(resolved.satisfied)

    def test_failure_normalizer_redacts_private_details_and_is_stable(self):
        first = FailureNormalizer.normalize(
            capability_id="test.run", operation="focused", status="failed",
            events=(TaskEventDraft(
                event_type="task.failed",
                payload={"code": "tests_failed", "reason": "secret path C:/private/token"},
            ),),
        )
        second = FailureNormalizer.normalize(
            capability_id="test.run", operation="focused", status="failed",
            events=(TaskEventDraft(
                event_type="task.failed",
                payload={"code": "tests_failed", "reason": "different private detail"},
            ),),
        )

        self.assertEqual(first.signature, second.signature)
        self.assertNotIn("secret", first.safe_summary)
        self.assertNotIn("private", first.safe_summary)

    def test_repair_guard_blocks_unchanged_repetition_and_budget_exhaustion(self):
        guard = RepairLoopGuard(max_attempts_per_criterion=2)
        first = guard.record("tests", "failure-a", "call-a", "sha256:" + "1" * 64)
        repeated = guard.record("tests", "failure-a", "call-a", "sha256:" + "1" * 64)
        changed = guard.record("tests", "failure-b", "call-b", "sha256:" + "2" * 64)
        exhausted = guard.record("tests", "failure-c", "call-c", "sha256:" + "3" * 64)

        self.assertTrue(first.allowed)
        self.assertEqual(repeated.reason, "unchanged repair loop")
        self.assertTrue(changed.allowed)
        self.assertEqual(exhausted.reason, "repair budget exhausted")


if __name__ == "__main__":
    unittest.main()
