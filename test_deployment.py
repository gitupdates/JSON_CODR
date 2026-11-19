import unittest

from web_app.core.canonical import canonical_digest
from web_app.core.deployment import DeploymentRegistry, DeploymentService
from web_app.core.external_effects import ExternalTarget, RollbackClass


class FakeDeploymentAdapter:
    adapter_id = "fake.deploy"
    version = "1"
    rollback_class = RollbackClass.provider

    def __init__(self):
        self.fingerprint = canonical_digest({"remote": 1})
        self.applied = 0

    def remote_fingerprint(self, target):
        return self.fingerprint

    def preview(self, target, plan):
        return canonical_digest(plan), "one service update"

    def apply(self, target, plan):
        self.applied += 1
        self.fingerprint = canonical_digest({"remote": self.applied + 1})
        return self.fingerprint

    def health(self, target):
        return True

    def rollback(self, target, receipt):
        self.fingerprint = receipt.remote_fingerprint_before
        return self.fingerprint


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeDeploymentAdapter()
        self.registry = DeploymentRegistry()
        self.registry.register(self.adapter)
        self.service = DeploymentService(self.registry)
        self.target = ExternalTarget(
            provider="fake", account="account", region="local", service="app",
            environment="staging", credential_ref="credential:test",
        )

    def test_disabled_default_preview_apply_health_and_separate_rollback(self):
        with self.assertRaisesRegex(PermissionError, "disabled"):
            self.service.preview("fake.deploy", self.target, {"image": "v2"})
        self.registry.enable("fake.deploy")
        preview = self.service.preview("fake.deploy", self.target, {"image": "v2"})
        with self.assertRaisesRegex(PermissionError, "digest"):
            self.service.apply(preview, approved_plan_digest=canonical_digest({"image": "other"}))
        receipt = self.service.apply(preview, approved_plan_digest=preview.plan_digest)
        self.assertEqual(receipt.status, "healthy")
        with self.assertRaisesRegex(PermissionError, "separate approval"):
            self.service.rollback("fake.deploy", self.target, receipt.effect_id, approved=False)
        self.assertEqual(
            self.service.rollback("fake.deploy", self.target, receipt.effect_id, approved=True).status,
            "rolled_back",
        )

    def test_stale_preview_and_production_need_stronger_confirmation(self):
        self.registry.enable("fake.deploy")
        preview = self.service.preview("fake.deploy", self.target, {"image": "v2"})
        self.adapter.fingerprint = canonical_digest({"remote": "changed"})
        with self.assertRaisesRegex(PermissionError, "drifted"):
            self.service.apply(preview, approved_plan_digest=preview.plan_digest)
        production = self.target.model_copy(update={"environment": "production"})
        preview = self.service.preview("fake.deploy", production, {"image": "v2"})
        with self.assertRaisesRegex(PermissionError, "stronger"):
            self.service.apply(preview, approved_plan_digest=preview.plan_digest)
        self.assertEqual(
            self.service.apply(preview, approved_plan_digest=preview.plan_digest, strong_confirmation=True).status,
            "healthy",
        )


if __name__ == "__main__":
    unittest.main()
