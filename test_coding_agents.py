import tempfile
import unittest
from pathlib import Path

from web_app.coding_agents import CodingAgentService


class CodingAgentAuthorizationTests(unittest.TestCase):
    def test_full_grant_persists_and_is_bound_to_project_and_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            nested = project / "src"
            outside = root / "outside"
            nested.mkdir(parents=True)
            outside.mkdir()
            service = CodingAgentService(root / "data", executable_finder=lambda name: None)

            grant = service.grant(project, "aider")
            reloaded = CodingAgentService(root / "data", executable_finder=lambda name: None)

            self.assertEqual(grant.scope, "full")
            self.assertTrue(reloaded.authorized(nested, "aider"))
            self.assertFalse(reloaded.authorized(nested, "continue"))
            self.assertFalse(reloaded.authorized(outside, "aider"))

    def test_revoked_grant_no_longer_authorizes_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            service = CodingAgentService(root / "data", executable_finder=lambda name: None)
            grant = service.grant(project, "continue")

            service.revoke(grant.id)

            self.assertFalse(service.authorized(project, "continue"))
            self.assertFalse(next(item for item in service.status()["grants"] if item["id"] == grant.id)["enabled"])

    def test_missing_or_reparse_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = CodingAgentService(root / "data", executable_finder=lambda name: None)
            with self.assertRaisesRegex(ValueError, "existing directory"):
                service.grant(root / "missing", "aider")

            project = root / "project"
            project.mkdir()
            link = root / "linked-project"
            try:
                link.symlink_to(project, target_is_directory=True)
            except OSError:
                self.skipTest("Directory symlinks are unavailable")
            with self.assertRaisesRegex(ValueError, "reparse"):
                service.grant(link, "aider")


class CodingAgentAdapterTests(unittest.TestCase):
    def _service(self, root: Path) -> CodingAgentService:
        return CodingAgentService(root / "data", executable_finder=lambda name: f"C:/tools/{name}.exe")

    def test_continue_interactive_and_delegated_plans_use_local_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            service = self._service(root)
            service.grant(project, "continue")

            interactive = service.launch_plan("continue", project, "qwen2.5-coder:7b", "interactive")
            delegated = service.launch_plan("continue", project, "qwen2.5-coder:7b", "delegated", "Fix tests")

            self.assertEqual(interactive.argv, ("C:/tools/cn.exe", "--model", "ollama/qwen2.5-coder:7b"))
            self.assertEqual(delegated.argv, (
                "C:/tools/cn.exe", "-p", "Fix tests", "--allow", "Read", "--allow", "Write", "--allow", "Edit",
                "--exclude", "Bash", "--model", "ollama/qwen2.5-coder:7b"
            ))
            self.assertTrue(interactive.interactive)
            self.assertFalse(delegated.interactive)

    def test_aider_plan_uses_ollama_chat_and_local_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            service = self._service(root)
            service.grant(project, "aider")

            plan = service.launch_plan("aider", project, "qwen2.5-coder:7b", "interactive")

            self.assertEqual(plan.argv, ("C:/tools/aider.exe", "--model", "ollama_chat/qwen2.5-coder:7b"))
            self.assertEqual(plan.environment["OLLAMA_API_BASE"], "http://127.0.0.1:11434")

            delegated = service.launch_plan("aider", project, "qwen2.5-coder:7b", "delegated", "Fix tests")
            self.assertIn("--subtree-only", delegated.argv)
            self.assertIn("--no-suggest-shell-commands", delegated.argv)
            self.assertIn("--no-auto-commits", delegated.argv)

    def test_launch_requires_installed_tool_valid_model_and_matching_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            service = CodingAgentService(root / "data", executable_finder=lambda name: None)
            service.grant(project, "aider")
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                service.launch_plan("aider", project, "qwen2.5-coder:7b", "interactive")

            available = self._service(root)
            with self.assertRaisesRegex(PermissionError, "persistent authorization"):
                available.launch_plan("continue", project, "qwen2.5-coder:7b", "interactive")
            with self.assertRaisesRegex(ValueError, "model name"):
                available.launch_plan("aider", project, "qwen; Remove-Item", "interactive")


if __name__ == "__main__":
    unittest.main()
