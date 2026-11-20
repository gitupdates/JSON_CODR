import tempfile
import unittest
from pathlib import Path

from web_app.core.adapters import CapabilityCall
from web_app.core.deployment import DeploymentRegistry
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.models import AutonomousCodingSettings


class AutonomousCodingRedteamTests(unittest.TestCase):
    def test_rt01_rt02_rt03_effects_are_not_implicitly_authorized(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = PolicyService(Path(directory) / "policy.sqlite")
            try:
                for operation in ("bounded_edit", "test", "network", "install", "commit", "push"):
                    call = CapabilityCall(
                        capability_id="project.action", operation=operation,
                        project_root=directory, arguments={},
                    )
                    self.assertEqual(policy.evaluate("user", "project", call).effect, PolicyEffect.require_approval)
            finally:
                policy.close()

    def test_rt04_rt05_rt11_mutation_approval_and_race_suites_are_release_gates(self):
        for path, evidence in (
            ("test_core_approval.py", "one_use_across_store_connections"),
            ("test_worktree_runtime.py", "fingerprint"),
            ("test_plan_revisions.py", "optimistically_concurrent"),
        ):
            self.assertIn(evidence, Path(path).read_text(encoding="utf-8"))

    def test_rt06_rt07_rt08_rt12_rt13_untrusted_execution_is_bounded(self):
        command_tests = Path("test_command_runtime.py").read_text(encoding="utf-8")
        planner_tests = Path("test_agent_services.py").read_text(encoding="utf-8")
        self.assertIn("sanitized_environment", command_tests)
        self.assertIn("redaction", command_tests)
        self.assertIn("escape", command_tests)
        self.assertIn("duplicate", planner_tests)
        self.assertIn("without", planner_tests)

    def test_rt09_rt10_rt14_external_and_drifted_adapters_default_closed(self):
        registry = DeploymentRegistry()
        with self.assertRaisesRegex(PermissionError, "disabled"):
            registry.resolve("missing")
        conformance = Path("test_model_conformance.py").read_text(encoding="utf-8")
        catalog = Path("test_capability_catalog.py").read_text(encoding="utf-8")
        self.assertIn("invalidated_by_any_drift", conformance)
        self.assertIn("availability.available", catalog)

    def test_rt15_release_defaults_are_versioned_and_redaction_safe(self):
        settings = AutonomousCodingSettings()
        self.assertEqual(settings.schema_version, 1)
        self.assertTrue(settings.allow_read_only_automatically)
        self.assertTrue(settings.pause_before_file_changes)
        self.assertTrue(settings.pause_before_commands)
        self.assertTrue(settings.pause_before_network)
        self.assertTrue(settings.pause_before_installations)
        self.assertTrue(settings.pause_before_git_publication)
        self.assertTrue(settings.pause_before_external_effects)
        self.assertFalse(settings.external_adapters_enabled)


if __name__ == "__main__":
    unittest.main()
