import unittest

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import ProviderKind
from web_app.inference.router import InferenceRouter
from web_app.models import ChatResult


class FakeOllama:
    def __init__(self, installed=None):
        self.installed = installed or ["qwen2.5-coder:0.5b"]
        self.calls = []

    async def list_models(self):
        return [{"name": name, "installed": True} for name in self.installed]

    async def chat(self, model, prompt, images=None, allow_repair=True):
        self.calls.append(model)
        return ChatResult(model=model, status="ok", summary="ollama", content="done")

    async def supports_vision(self, model):
        return model.endswith("vision")

    async def stream_chat(self, model, prompt, images=None, public_reasoning=False):
        self.calls.append((model, public_reasoning))
        yield {"type": "content", "text": "live"}
        yield {
            "type": "completed",
            "result": ChatResult(model=model, status="ok", summary="live", content="live"),
        }


class FakeProvider:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def chat(self, model, prompt, images=None):
        self.calls.append(model.id)
        if self.error:
            raise self.error
        return ChatResult(model=model.id, status="ok", summary="accelerated", content="done")


class FakeRegistry:
    def __init__(self, provider):
        self.provider = provider

    def get(self, kind):
        return self.provider


class CanonicalFakeOllama(FakeOllama):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def generate(self, request):
        from web_app.inference.protocol import InferenceEvent

        self.requests.append(request)
        yield InferenceEvent(
            type="content",
            text="live",
            requested_model=request.model,
            effective_model=request.model,
            route="ollama",
        )
        yield InferenceEvent(
            type="completed",
            requested_model=request.model,
            effective_model=request.model,
            route="ollama",
            finish_reason="stop",
        )


class InferenceRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_optimized_inventory_exposes_runnable_state(self):
        catalog = OptimizedModelCatalog()
        model = catalog.list()[0]
        router = InferenceRouter(
            FakeOllama(), catalog, FakeRegistry(FakeProvider()), {model.id},
        )

        records = await router.list_models()
        optimized = next(item for item in records if item["name"] == model.id)

        self.assertTrue(optimized["installed"])
        self.assertTrue(optimized["runnable"])
        self.assertEqual(optimized["compatibility_status"], "verified")

        router.quarantined[model.id] = "provider probe failed"
        quarantined = next(
            item for item in await router.list_models() if item["name"] == model.id
        )
        self.assertFalse(quarantined["runnable"])
        self.assertEqual(quarantined["compatibility_status"], "quarantined")
        self.assertEqual(quarantined["fallback_reason"], "provider probe failed")

    async def test_generate_forwards_the_ordered_canonical_request(self):
        from web_app.inference.protocol import ContentPart, InferenceMessage, InferenceRequest

        ollama = CanonicalFakeOllama()
        router = InferenceRouter(ollama, OptimizedModelCatalog(), FakeRegistry(FakeProvider()), set())
        request = InferenceRequest(
            model="qwen3:4b",
            messages=(
                InferenceMessage(role="system", content=(ContentPart(type="text", text="Be exact."),)),
                InferenceMessage(role="user", content=(ContentPart(type="text", text="Answer."),)),
            ),
        )

        events = [event async for event in router.generate(request)]

        self.assertIs(ollama.requests[0], request)
        self.assertEqual([message.role for message in ollama.requests[0].messages], ["system", "user"])
        self.assertEqual([event.type for event in events], ["content", "completed"])

    async def test_vision_capability_uses_ollama_and_treats_optimized_catalog_as_text_only(self):
        router = InferenceRouter(FakeOllama(), OptimizedModelCatalog(), FakeRegistry(FakeProvider()), set())

        self.assertTrue(await router.supports_vision("local-vision"))
        self.assertFalse(await router.supports_vision(OptimizedModelCatalog().list()[0].id))

    async def test_unqualified_models_stream_directly_from_ollama(self):
        ollama = FakeOllama()
        router = InferenceRouter(ollama, OptimizedModelCatalog(), FakeRegistry(FakeProvider()), verified_models=set())

        events = [
            event async for event in router.stream_chat(
                "qwen2.5-coder:0.5b",
                "hello",
                public_reasoning=True,
            )
        ]

        self.assertEqual([event["type"] for event in events], ["content", "completed"])
        self.assertEqual(ollama.calls, [("qwen2.5-coder:0.5b", True)])

    async def test_unqualified_models_use_only_ollama(self):
        ollama = FakeOllama()
        provider = FakeProvider()
        router = InferenceRouter(ollama, OptimizedModelCatalog(), FakeRegistry(provider), verified_models=set())

        result = await router.chat("qwen2.5-coder:0.5b", "hello")

        self.assertEqual(result.model, "qwen2.5-coder:0.5b")
        self.assertEqual(ollama.calls, ["qwen2.5-coder:0.5b"])
        self.assertEqual(provider.calls, [])

    async def test_qualified_model_routes_to_provider_when_verified(self):
        model = OptimizedModelCatalog().list()[1]
        provider = FakeProvider()
        router = InferenceRouter(FakeOllama(), OptimizedModelCatalog(), FakeRegistry(provider), {model.id})

        result = await router.chat(model.id, "hello")

        self.assertEqual(result.model, model.id)
        self.assertEqual(provider.calls, [model.id])

    async def test_provider_failure_quarantines_pair_and_uses_mapped_then_cpu_fallback(self):
        catalog = OptimizedModelCatalog()
        model = catalog.list()[1]
        ollama = FakeOllama([model.ollama_fallback])
        router = InferenceRouter(ollama, catalog, FakeRegistry(FakeProvider(RuntimeError("NPU crashed"))), {model.id})

        result = await router.chat(model.id, "hello")

        self.assertEqual(ollama.calls, [model.ollama_fallback])
        self.assertIn("Fallback", result.summary)
        self.assertEqual(result.provider_events[0]["type"], "provider_fallback")
        self.assertEqual(result.provider_events[0]["effective_model"], model.ollama_fallback)
        self.assertIn(model.id, router.quarantined)

        ollama = FakeOllama(["another-coder:latest"])
        router = InferenceRouter(ollama, catalog, FakeRegistry(FakeProvider(RuntimeError("failed"))), {model.id})
        result = await router.chat(model.id, "hello")
        self.assertEqual(ollama.calls, ["another-coder:latest"])
        self.assertIn("another-coder:latest", result.summary)


if __name__ == "__main__":
    unittest.main()
