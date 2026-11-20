import asyncio
import unittest

from web_app.core.provider_compatibility import (
    CompatibilityLayer,
    ProviderActivation,
    ProviderEvidence,
    ProviderUpdateRequest,
)


class FakeAdapter:
    provider_id = "example"

    def __init__(self, *, evidence=True):
        self.requests = []
        self.evidence = evidence

    async def update(self, request):
        self.requests.append(request)
        proof = None
        if self.evidence:
            proof = ProviderEvidence(
                provider_id="example",
                version=request.version,
                probe="example.health",
                evidence_digest="sha256:" + "1" * 64,
                details={"live": True},
            )
        return ProviderActivation(
            provider_id="example",
            version=request.version,
            generation=3,
            evidence=proof,
        )


class ProviderCompatibilityTests(unittest.TestCase):
    def test_routes_exact_request_to_registered_adapter(self):
        adapter = FakeAdapter()
        layer = CompatibilityLayer([adapter])

        result = asyncio.run(layer.update(ProviderUpdateRequest(
            provider_id="example", version="1.2.3", approve_major=True
        )))

        self.assertEqual(result.version, "1.2.3")
        self.assertEqual(result.evidence.details, {"live": True})
        self.assertEqual(adapter.requests[0].approve_major, True)

    def test_rejects_unknown_provider_instead_of_guessing(self):
        layer = CompatibilityLayer([])

        with self.assertRaisesRegex(LookupError, "not registered"):
            asyncio.run(layer.update(ProviderUpdateRequest(provider_id="missing", version="1.2.3")))

    def test_rejects_activation_without_real_probe_evidence(self):
        layer = CompatibilityLayer([FakeAdapter(evidence=False)])

        with self.assertRaisesRegex(RuntimeError, "verification evidence"):
            asyncio.run(layer.update(ProviderUpdateRequest(provider_id="example", version="1.2.3")))

    def test_rejects_adapter_identity_substitution(self):
        adapter = FakeAdapter()
        adapter.provider_id = "other"
        layer = CompatibilityLayer([adapter])

        with self.assertRaisesRegex(LookupError, "not registered"):
            asyncio.run(layer.update(ProviderUpdateRequest(provider_id="example", version="1.2.3")))


if __name__ == "__main__":
    unittest.main()
