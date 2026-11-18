import tempfile
import unittest
from pathlib import Path

from web_app.core.contracts import (
    EffectClass,
    PlanReviewStatus,
    PlanRevision,
    PlannedStep,
    StepDisposition,
    TaskCommand,
    TaskEventDraft,
    TaskPhase,
)
from web_app.core.store import ConcurrencyConflict, TaskStore


def command() -> TaskCommand:
    return TaskCommand(
        command_id="command-task-1", task_id="task-1", thread_id="thread-1",
        project_id="project-1", command_type="agent.run", payload={},
    )


def plan(revision=1, *, parent_revision=None, disposition=StepDisposition.pending, path="src/app.py"):
    step = PlannedStep(
        step_id="step-1", plan_id="plan-1", plan_revision=revision,
        criterion_ids=("verified",), title="Inspect project", purpose="Gather evidence",
        capability_id="project.read", operation="read", target_path=path,
        arguments={"path": path}, effect_class=EffectClass.observe,
        disposition=disposition,
    )
    return PlanRevision(
        plan_id="plan-1", revision=revision, goal_id="goal-1", goal_revision=1,
        summary="Inspect project", expected_deliverables=("evidence",),
        parent_revision=parent_revision, review_status=PlanReviewStatus.in_review,
        steps=(step,),
    )


class PlanStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "tasks.sqlite"
        self.store = TaskStore(self.database)
        self.store.create(command())

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_revision_round_trips_after_database_reopen(self):
        stored = self.store.append_plan("task-1", plan())
        self.store.close()
        self.store = TaskStore(self.database)

        self.assertEqual(self.store.plan("task-1", "plan-1", 1), stored)
        self.assertEqual(self.store.plans("task-1"), (stored,))
        self.assertIn("agent.plan_revision_created", [event.event_type for event in self.store.events("task-1")])

    def test_expected_digest_rejects_stale_revision_append(self):
        first = self.store.append_plan("task-1", plan())

        with self.assertRaises(ConcurrencyConflict):
            self.store.append_plan(
                "task-1", plan(2, parent_revision=1),
                expected_current_digest="sha256:" + "f" * 64,
            )

        second = self.store.append_plan(
            "task-1", plan(2, parent_revision=1),
            expected_current_digest=first.canonical_digest,
        )
        self.assertEqual(second.revision, 2)

    def test_duplicate_decision_is_idempotent_and_rejection_is_final(self):
        current = self.store.append_plan("task-1", plan())

        rejected = self.store.record_plan_decision(
            "task-1", "plan-1", 1, "reject", principal="user",
            expected_plan_digest=current.canonical_digest, reason="Change the target",
        )
        replayed = self.store.record_plan_decision(
            "task-1", "plan-1", 1, "reject", principal="user",
            expected_plan_digest=current.canonical_digest, reason="Change the target",
        )

        self.assertEqual(rejected, replayed)
        self.assertEqual(self.store.plan_decisions("task-1", "plan-1", 1), (rejected,))
        with self.assertRaises(ConcurrencyConflict):
            self.store.record_plan_decision(
                "task-1", "plan-1", 1, "approve", principal="user",
                expected_plan_digest=current.canonical_digest,
            )

    def test_completed_step_carry_forward_requires_same_digest(self):
        self.store.append_plan("task-1", plan(disposition=StepDisposition.completed))

        with self.assertRaisesRegex(ConcurrencyConflict, "completed step"):
            self.store.append_plan(
                "task-1",
                plan(2, parent_revision=1, disposition=StepDisposition.completed, path="src/other.py"),
            )

    def test_phase_is_derived_from_events_and_terminal_status(self):
        self.assertEqual(self.store.phase("task-1"), TaskPhase.describe)
        self.store.append(
            "task-1", TaskEventDraft(event_type="agent.phase_changed", payload={"phase": "plan_review"}),
        )
        self.assertEqual(self.store.phase("task-1"), TaskPhase.plan_review)
        self.store.append("task-1", TaskEventDraft(event_type="task.cancelled"))
        self.assertEqual(self.store.phase("task-1"), TaskPhase.cancelled)


if __name__ == "__main__":
    unittest.main()
