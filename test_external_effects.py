import unittest

from web_app.core.external_effects import ExternalTarget


class ExternalTargetTests(unittest.TestCase):
    def test_target_digest_binds_every_routing_and_credential_field(self):
        target = ExternalTarget(
            provider="azure", account="tenant-a", subscription="sub-a", region="centralus",
            cluster="cluster-a", namespace="apps", service="json-codr",
            environment="staging", credential_ref="credential:azure-staging",
        )
        self.assertTrue(target.target_digest.startswith("sha256:"))
        self.assertNotEqual(target.target_digest, target.model_copy(update={"region": "eastus"}).target_digest)
        self.assertNotIn("secret", target.model_dump_json())


if __name__ == "__main__":
    unittest.main()
