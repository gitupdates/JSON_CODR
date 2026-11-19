import tempfile
import unittest
from pathlib import Path

from web_app.core.contracts import PlanRevision, PlannedStep, TaskCommand
from web_app.core.store import ConcurrencyConflict, TaskStore


class PlanRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temporary.name) / "tasks.sqlite")
        self.store.create(TaskCommand(
            command_id="command-1", task_id="task-1", thread_id="thread-1",
            project_id="project-1", command_type="agent.run",
        ))

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def plan(self, revision, operation="read"):
        first = PlannedStep(
            step_id="step-1", plan_id="plan-1", plan_revision=revision,
            criterion_ids=("criterion-1",), capability_id="project.read",
            operation=operation,
        )
        second = PlannedStep(
            step_id="step-2", plan_id="plan-1", plan_revision=revision,
            criterion_ids=("criterion-1",), capability_id="test.run",
            operation="test", depends_on=("step-1",),
        )
        return PlanRevision(
            plan_id="plan-1", revision=revision, goal_id="goal-1",
            goal_revision=1, steps=(first, second),
        )

    def test_history_is_immutable_ordered_and_optimistically_concurrent(self):
        first = self.store.save_plan_revision("task-1", self.plan(1), expected_revision=None)
        second = self.store.save_plan_revision("task-1", self.plan(2, "search"), expected_revision=1)
        self.assertEqual(self.store.plan_revisions("task-1", "plan-1"), (first, second))
        with self.assertRaises(ConcurrencyConflict):
            self.store.save_plan_revision("task-1", self.plan(3), expected_revision=1)

    def test_dependencies_must_exist_and_point_backwards(self):
        with self.assertRaisesRegex(ValueError, "depend on itself|earlier"):
            PlanRevision(
                plan_id="plan-1", revision=1, goal_id="goal-1", goal_revision=1,
                steps=(PlannedStep(
                    step_id="step-1", plan_id="plan-1", plan_revision=1,
                    criterion_ids=("criterion-1",), capability_id="test.run",
                    operation="test", depends_on=("step-1",),
                ),),
            )


if __name__ == "__main__":
    unittest.main()
