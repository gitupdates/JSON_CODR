import unittest

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import ProviderKind
from web_app.inference.providers.registry import ProviderRegistry


class FakeSidecar:
    def __init__(self):
        self.calls = []

    async def request(self, operation, payload, timeout=120):
        self.calls.append((operation, payload))
        if operation == "chat":
            return {"model": payload["model_id"], "status": "ok", "summary": "ready", "content": "done"}
        return {"status": "ready"}


class ProviderAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_requires_the_expected_non_empty_response(self):
        model = OptimizedModelCatalog().list()[0]

        class ProbeSidecar:
            def __init__(self, content):
                self.content = content

            async def request(self, operation, payload, timeout=120):
                return {"model": payload["model_id"], "status": "success", "summary": "probe", "content": self.content}

        blank = await ProviderRegistry({ProviderKind.openvino: ProbeSidecar("  ")}).get(
            ProviderKind.openvino
        ).probe(model)
        expected = await ProviderRegistry({ProviderKind.openvino: ProbeSidecar(" OK\n")}).get(
            ProviderKind.openvino
        ).probe(model)

        self.assertFalse(blank.success)
        self.assertIn("expected", blank.error)
        self.assertTrue(expected.success)

    async def test_provider_device_selection_and_structured_chat(self):
        catalog = OptimizedModelCatalog()
        clients = {provider: FakeSidecar() for provider in ProviderKind if provider is not ProviderKind.ollama}
        registry = ProviderRegistry(clients)

        openvino = catalog.get("openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov")
        result = await registry.get(ProviderKind.openvino).chat(openvino, "hello")
        self.assertEqual(result.status, "ok")
        self.assertEqual(clients[ProviderKind.openvino].calls[-1][1]["device"], "NPU")

        ryzen = catalog.get("ryzen_ai/amd/Qwen2.5-Coder-0.5B-Instruct_rai_1.8.0_m1.0_npu")
        await registry.get(ProviderKind.ryzen_ai).chat(ryzen, "hello")
        self.assertEqual(clients[ProviderKind.ryzen_ai].calls[-1][1]["provider"], "ryzen_ai")

    async def test_provider_rejects_mismatched_model_before_sidecar_launch(self):
        clients = {ProviderKind.openvino: FakeSidecar(), ProviderKind.directml: FakeSidecar()}
        registry = ProviderRegistry(clients)
        model = OptimizedModelCatalog().list()[0]

        with self.assertRaisesRegex(ValueError, "provider"):
            await registry.get(ProviderKind.directml).chat(model, "hello")
        self.assertEqual(clients[ProviderKind.directml].calls, [])


if __name__ == "__main__":
    unittest.main()
