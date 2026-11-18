import unittest
from pathlib import Path


class GuidedTaskUiTests(unittest.TestCase):
    def test_four_phase_review_interface_is_visible_and_accessible(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        for identifier in (
            "task-phase-stepper", "task-phase-describe", "task-phase-plan",
            "task-phase-execute", "task-phase-deliver", "task-plan-panel",
            "task-changes-panel", "task-results-panel", "task-plan-summary",
            "task-plan-steps", "task-revision-history", "task-artifacts",
            "task-review-announcer",
        ):
            self.assertIn(f'id="{identifier}"', html)
        for label in ("Describe", "Plan", "Execute", "Deliver"):
            self.assertIn(f">{label}<", html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('role="tablist" aria-label="Task views"', html)

    def test_task_client_and_view_cover_review_revision_conflict_and_delivery(self):
        client = Path("web/core_client.js").read_text(encoding="utf-8")
        view = Path("web/task_view.js").read_text(encoding="utf-8")
        for method in (
            "listPlans", "approvePlan", "rejectPlan", "approveStep", "rejectStep",
            "editStep", "revisePlan", "taskDelivery", "applyPolicy", "refreshBaseline",
        ):
            self.assertIn(f"{method}(", client)
        self.assertIn("expected_plan_digest", client)
        for contract in (
            "current_digest", "revision history",
            "strong confirmation", "task-artifact-card", "aria-current",
        ):
            self.assertIn(contract, view.lower())

    def test_guided_styles_include_narrow_and_reduced_motion_modes(self):
        css = Path("web/gamma.css").read_text(encoding="utf-8")
        for selector in (
            ".task-phase-stepper", ".task-plan-step", ".task-effect-badge",
            ".task-artifact-card", ".task-review-actions",
        ):
            self.assertIn(selector, css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)


if __name__ == "__main__":
    unittest.main()
