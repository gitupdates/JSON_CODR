import unittest

from web_app.core.adapters import CapabilityCall


class AdapterFallbackTests(unittest.TestCase):
    def test_prefers_verified_native_capability(self):
        from web_app.core.adapter_fallback import AdapterFallbackRouter

        call = CapabilityCall(
            capability_id="native.read",
            operation="read",
            project_root=".",
            target_path="README.md",
        )
        route = AdapterFallbackRouter.resolve(call, {"native.read"}, {"native.read", "mcp.rea"})

        self.assertEqual(route.kind, "native")
        self.assertEqual(route.capability_id, "native.read")

    def test_routes_explicit_bridge_capability_to_compatibility_adapter(self):
        from web_app.core.adapter_fallback import AdapterFallbackRouter

        call = CapabilityCall(
            capability_id="mcp.rea",
            operation="invoke",
            project_root=".",
            arguments={"tool": "open_binary", "arguments": {}},
        )
        route = AdapterFallbackRouter.resolve(call, {"native.read"}, {"mcp.rea"})

        self.assertEqual(route.kind, "compatibility")
        self.assertEqual(route.capability_id, "mcp.rea")

    def test_does_not_claim_an_unavailable_capability(self):
        from web_app.core.adapter_fallback import AdapterFallbackRouter

        call = CapabilityCall(capability_id="mcp.missing", operation="invoke", project_root=".")
        route = AdapterFallbackRouter.resolve(call, {"native.read"}, {"mcp.rea"})

        self.assertEqual(route.kind, "unavailable")
        self.assertIsNone(route.capability_id)


if __name__ == "__main__":
    unittest.main()
