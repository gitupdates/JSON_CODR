import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from web_app.coding_agents import CodingAgentService


class CodingAgentAuthorizationTests(unittest.TestCase):
    def test_broker_and_shell_profiles_persist_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            service = CodingAgentService(root / "data", executable_finder=lambda name: None)

            broker = service.grant(project, "broker")
            service.grant(project, "shell")
            reloaded = CodingAgentService(root / "data", executable_finder=lambda name: None)

            self.assertTrue(reloaded.authorized(project, "broker"))
            self.assertTrue(reloaded.authorized(project, "shell"))
            reloaded.revoke(broker.id)
            self.assertFalse(reloaded.authorized(project, "broker"))
            self.assertTrue(reloaded.authorized(project, "shell"))

    def test_legacy_tool_grant_is_read_as_matching_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            data = root / "data"
            data.mkdir()
            (data / "coding-agent-grants.json").write_text(json.dumps([{
                "id": "legacy", "project_root": str(project.resolve()), "tool": "aider", "scope": "full",
                "enabled": True, "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
            }]), encoding="utf-8")

            status = CodingAgentService(data, executable_finder=lambda name: None).status()

            self.assertEqual(status["grants"][0]["profile"], "aider")
            self.assertTrue(status["grants"][0]["enabled"])
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

            with patch.dict("os.environ", {"GHIDRA_INSTALL_DIR": "C:/tools/ghidra", "JAVA_HOME": "C:/tools/jdk"}):
                interactive = service.launch_plan("continue", project, "qwen2.5-coder:7b", "interactive")
                delegated = service.launch_plan("continue", project, "qwen2.5-coder:7b", "delegated", "Fix tests")

            config = Path(interactive.argv[2])
            self.assertEqual(interactive.argv[:2], ("C:/tools/cn.exe", "--config"))
            self.assertTrue(config.is_file())
            self.assertIn("provider: ollama", config.read_text(encoding="utf-8"))
            self.assertIn("model: qwen2.5-coder:7b", config.read_text(encoding="utf-8"))
            self.assertIn("mcpServers:", config.read_text(encoding="utf-8"))
            self.assertIn("name: REA reverse engineering", config.read_text(encoding="utf-8"))
            self.assertIn("GHIDRA_INSTALL_DIR:", config.read_text(encoding="utf-8"))
            self.assertEqual(delegated.argv, (
                "C:/tools/cn.exe", "-p", "Fix tests", "--allow", "Read", "--allow", "Write", "--allow", "Edit",
                "--exclude", "Bash", "--config", str(config)
            ))
            self.assertTrue(interactive.interactive)
            self.assertFalse(delegated.interactive)

            limited = service.launch_plan(
                "continue", project, "opencoder:8b", "delegated", "Inspect", supports_tools=False
            )
            limited_config = Path(limited.argv[-1]).read_text(encoding="utf-8")
            self.assertNotIn("tool_use", limited_config)
            self.assertIn("onlyUseSystemMessageTools: true", limited_config)
            self.assertNotIn("mcpServers:", limited_config)
            self.assertNotIn("--allow", limited.argv)
            for tool in ("Read", "Write", "Edit", "Fetch", "MultiEdit", "Bash", "Skills"):
                self.assertIn(tool, limited.argv)

    def test_aider_plan_uses_ollama_chat_and_local_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            service = self._service(root)
            service.grant(project, "aider")

            with patch.dict("os.environ", {"GHIDRA_INSTALL_DIR": "C:/tools/ghidra", "JAVA_HOME": "C:/tools/jdk"}):
                plan = service.launch_plan("aider", project, "qwen2.5-coder:7b", "interactive")

            self.assertEqual(plan.argv[:3], ("C:/tools/aider.exe", "--model", "ollama_chat/qwen2.5-coder:7b"))
            self.assertIn("--no-check-update", plan.argv)
            self.assertIn("--no-fancy-input", plan.argv)
            self.assertIn("--no-show-model-warnings", plan.argv)
            self.assertIn("--set-env", plan.argv)
            self.assertIn("OLLAMA_API_BASE=http://127.0.0.1:11434", plan.argv)
            self.assertEqual(plan.environment["OLLAMA_API_BASE"], "http://127.0.0.1:11434")
            self.assertIn("GHIDRA_INSTALL_DIR", plan.environment)
            self.assertIn("JAVA_HOME", plan.environment)

            with patch.dict("os.environ", {"GHIDRA_INSTALL_DIR": "C:/tools/ghidra", "JAVA_HOME": "C:/tools/jdk"}):
                delegated = service.launch_plan("aider", project, "qwen2.5-coder:7b", "delegated", "Fix tests")
            self.assertIn("--subtree-only", delegated.argv)
            self.assertIn("--no-suggest-shell-commands", delegated.argv)
            self.assertIn("--no-auto-commits", delegated.argv)
            self.assertIn("--no-check-update", delegated.argv)
            self.assertIn("--no-fancy-input", delegated.argv)
            self.assertIn("--no-pretty", delegated.argv)
            self.assertNotIn("--no-stream", delegated.argv)

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
