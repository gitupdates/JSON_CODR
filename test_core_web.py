import unittest
from pathlib import Path


class CoreWebContractTests(unittest.TestCase):
    def setUp(self):
        self.html = Path("web/index.html").read_text(encoding="utf-8")
        self.app = Path("web/app.js").read_text(encoding="utf-8")
        self.client = Path("web/core_client.js").read_text(encoding="utf-8")
        self.view = Path("web/task_view.js").read_text(encoding="utf-8")
        self.css = Path("web/app.css").read_text(encoding="utf-8")

    def test_one_task_flow_and_progressive_details_are_present(self):
        for identifier in (
            "task-activity", "task-steer", "task-stop", "task-retry", "task-undo",
            "task-execution-details", "task-requested-model", "task-effective-model",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("/api/tasks", self.client)
        self.assertIn("/ws/tasks", self.client)
        self.assertIn("after_sequence", self.client)
        self.assertIn("/steer", self.client)
        self.assertIn("/cancel", self.client)
        self.assertIn("/retry", self.client)
        self.assertIn("/restore", self.client)
        self.assertIn("requested_model_id", self.view)
        self.assertIn("effective_model_id", self.view)
        self.assertIn("task.permission_required", self.view)
        self.assertIn("details", self.html)

    def test_submission_drop_and_immediate_steering_share_the_task_store(self):
        self.assertIn("JSONCodrCoreClient", self.app)
        self.assertIn("JSONCodrTaskView", self.app)
        self.assertIn("coreClient.submit", self.app)
        self.assertIn('addEventListener("drop"', self.app)
        self.assertIn("activeCoreTaskId", self.app)
        self.assertIn("coreClient.steer", self.app)
        self.assertNotIn("Apply changes", self.html)

    def test_ui_has_no_executor_specific_product_controls_or_paths(self):
        for forbidden in (
            "Continue CLI", "Aider", "BETA CODING AGENTS", "coding-agent-tool",
            "/api/coding-agents", "/api/git-broker/adapter",
        ):
            self.assertNotIn(forbidden, self.html + self.app)
        self.assertIn("PowerShell", self.html)

    def test_layout_is_responsive_without_continuous_repainting(self):
        self.assertIn(".task-activity", self.css)
        self.assertIn("@media", self.css)
        self.assertNotIn("requestAnimationFrame", self.client + self.view)


if __name__ == "__main__":
    unittest.main()
