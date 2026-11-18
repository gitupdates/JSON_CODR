import tempfile
import unittest
from pathlib import Path

from web_app.core.adapters import CapabilityCall
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.models import ExecutionPolicySettings


class ExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = PolicyService(self.root / "policy.sqlite")

    def tearDown(self):
        self.policy.close()
        self.temporary.cleanup()

    def call(self, operation, capability="project.tool"):
        return CapabilityCall(
            capability_id=capability, operation=operation,
            project_root=str(self.root), target_path=str(self.root / "file.py"),
        )

    def test_presets_apply_the_authoritative_effect_table(self):
        expected = {
            "balanced": {
                "read": PolicyEffect.allow,
                "bounded_edit": PolicyEffect.require_approval,
                "test": PolicyEffect.require_approval,
                "network": PolicyEffect.require_approval,
                "destructive": PolicyEffect.strong_confirmation,
            },
            "strict": {
                "read": PolicyEffect.require_approval,
                "bounded_edit": PolicyEffect.require_approval,
                "test": PolicyEffect.require_approval,
                "network": PolicyEffect.require_approval,
                "destructive": PolicyEffect.strong_confirmation,
            },
            "autonomous": {
                "read": PolicyEffect.allow,
                "bounded_edit": PolicyEffect.allow,
                "test": PolicyEffect.allow,
                "network": PolicyEffect.require_approval,
                "destructive": PolicyEffect.strong_confirmation,
            },
        }
        for preset, decisions in expected.items():
            snapshot = self.policy.snapshot(ExecutionPolicySettings(preset=preset), "project-1")
            self.assertTrue(snapshot.requires_plan_approval)
            for operation, effect in decisions.items():
                with self.subTest(preset=preset, operation=operation):
                    self.assertEqual(
                        self.policy.evaluate(
                            "user", "project-1", self.call(operation), snapshot=snapshot,
                        ).effect,
                        effect,
                    )

    def test_override_precedence_and_hard_rules(self):
        settings = ExecutionPolicySettings(
            preset="strict",
            global_overrides={"project.tool": "allow"},
            project_overrides={"project-1": {"project.tool": "deny"}},
        )
        snapshot = self.policy.snapshot(settings, "project-1")

        self.assertEqual(
            self.policy.evaluate("user", "project-1", self.call("read"), snapshot=snapshot).effect,
            PolicyEffect.deny,
        )
        self.assertEqual(
            self.policy.evaluate(
                "user", "project-1", self.call("read"), snapshot=snapshot,
                task_denials=frozenset({"project.tool"}),
            ).effect,
            PolicyEffect.deny,
        )
        allow_destructive = self.policy.snapshot(
            ExecutionPolicySettings(global_overrides={"project.tool": "allow"}), "project-1",
        )
        self.assertEqual(
            self.policy.evaluate(
                "user", "project-1", self.call("destructive"), snapshot=allow_destructive,
            ).effect,
            PolicyEffect.strong_confirmation,
        )

    def test_snapshot_is_immutable_and_stable_after_settings_change(self):
        settings = ExecutionPolicySettings(preset="balanced")
        snapshot = self.policy.snapshot(settings, "project-1")
        digest = snapshot.canonical_digest
        settings.preset = "autonomous"

        self.assertEqual(snapshot.preset, "balanced")
        self.assertEqual(snapshot.canonical_digest, digest)
        self.assertEqual(
            self.policy.evaluate(
                "user", "project-1", self.call("bounded_edit"), snapshot=snapshot,
            ).effect,
            PolicyEffect.require_approval,
        )

    def test_unknown_connector_operation_defaults_to_approval(self):
        snapshot = self.policy.snapshot(ExecutionPolicySettings(preset="autonomous"), "project-1")

        decision = self.policy.evaluate(
            "user", "project-1", self.call("unclassified", capability="mcp.issues"),
            snapshot=snapshot,
        )

        self.assertEqual(decision.effect, PolicyEffect.require_approval)


if __name__ == "__main__":
    unittest.main()
