import json
import tempfile
import unittest
from pathlib import Path

import ollama

from web_app.ollama_service import OllamaService
from web_app.reasoning import ReasoningNormalizer


class ReasoningNormalizerTests(unittest.TestCase):
    def test_native_reasoning_and_content_remain_separate_with_provenance(self):
        normalizer = ReasoningNormalizer()

        deltas = normalizer.feed({"reasoning": "Compare both manifests. ", "content": "The result is "})
        deltas.extend(normalizer.feed({"content": "valid."}))
        deltas.extend(normalizer.finish())

        self.assertEqual("".join(item.text for item in deltas if item.channel == "reasoning"), "Compare both manifests. ")
        self.assertTrue(all(item.provenance == "native_provider" for item in deltas if item.channel == "reasoning"))
        self.assertEqual("".join(item.text for item in deltas if item.channel == "content"), "The result is valid.")

    def test_reasoning_tags_can_span_provider_chunks(self):
        normalizer = ReasoningNormalizer()

        deltas = normalizer.feed({"content": "<thi"})
        deltas.extend(normalizer.feed({"content": "nk>Check evidence</th"}))
        deltas.extend(normalizer.feed({"content": "ink>Final answer"}))
        deltas.extend(normalizer.finish())

        self.assertEqual("".join(item.text for item in deltas if item.channel == "reasoning"), "Check evidence")
        self.assertTrue(all(item.provenance == "provider_tag" for item in deltas if item.channel == "reasoning"))
        self.assertEqual("".join(item.text for item in deltas if item.channel == "content"), "Final answer")

    def test_unclosed_reasoning_tag_is_preserved_and_warned(self):
        normalizer = ReasoningNormalizer()

        deltas = normalizer.feed({"content": "<think>unfinished"})
        deltas.extend(normalizer.finish())

        self.assertEqual("".join(item.text for item in deltas if item.channel == "reasoning"), "unfinished")
        self.assertEqual([item.text for item in deltas if item.channel == "warning"], ["Provider reasoning tag was not closed"])

    def test_requested_public_rationale_has_distinct_provenance(self):
        deltas = ReasoningNormalizer().feed({"rationale": "I checked the schema."})

        self.assertEqual(deltas[0].channel, "reasoning")
        self.assertEqual(deltas[0].provenance, "public_rationale")


class OllamaPublicReasoningTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_requests_native_thinking_when_public_reasoning_is_enabled(self):
        class FakeStream:
            def __init__(self):
                self.chunks = iter([
                    {"message": {"thinking": "Verify inputs.", "content": ""}},
                    {"message": {"thinking": "", "content": "The answer."}},
                ])

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.chunks)
                except StopIteration:
                    raise StopAsyncIteration

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [{"model": "qwen3:4b"}]}

            async def chat(self, **request):
                self.calls.append(request)
                return FakeStream()

        client = FakeClient()
        service = OllamaService(client=client)

        events = [event async for event in service.stream_chat(
            "qwen3:4b", "Review", public_reasoning=True
        )]

        self.assertIs(client.calls[0]["think"], True)
        self.assertNotIn("<think>", client.calls[0]["messages"][0]["content"])
        self.assertEqual(events[0]["type"], "reasoning")
        self.assertEqual(events[-1]["result"].reasoning.entries[0].text, "Verify inputs.")

    async def test_stream_retries_without_thinking_when_error_is_deferred_until_iteration(self):
        class UnsupportedThinkingStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise ollama.ResponseError('model does not support thinking', 400)

        class ContentStream:
            def __init__(self):
                self.sent = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.sent:
                    raise StopAsyncIteration
                self.sent = True
                return {"message": {"content": "Fallback answer."}}

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [{"model": "qwen2.5-coder:0.5b"}]}

            async def chat(self, **request):
                self.calls.append(request)
                return UnsupportedThinkingStream() if request.get("think") else ContentStream()

        client = FakeClient()
        service = OllamaService(client=client)

        events = [event async for event in service.stream_chat(
            "qwen2.5-coder:0.5b", "Review", public_reasoning=True
        )]

        self.assertEqual([call.get("think") for call in client.calls], [True, None])
        self.assertEqual(events[-1]["result"].content, "Fallback answer.")

    async def test_stream_compatibility_falls_back_before_any_output(self):
        from web_app.model_compatibility import ModelCompatibilityLayer

        class ErrorStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise ollama.ResponseError("GGML_ASSERT failed to load model", 500)

        class ContentStream:
            def __init__(self):
                self.sent = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.sent:
                    raise StopAsyncIteration
                self.sent = True
                return {"message": {"content": "Fallback answer."}}

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [
                    {"model": "broken:8b", "digest": "sha256:" + "a" * 64},
                    {"model": "base:1b", "digest": "sha256:" + "b" * 64},
                ]}

            async def chat(self, **request):
                self.calls.append(request["model"])
                return ErrorStream() if request["model"] == "broken:8b" else ContentStream()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": 1,
                "base_fallback_order": ["base:1b"],
                "models": {},
            }), encoding="utf-8")
            compatibility = ModelCompatibilityLayer.load(policy, root / "state.json")
            client = FakeClient()
            service = OllamaService(client=client)
            service.set_compatibility_layer(compatibility)

            events = [event async for event in service.stream_chat("broken:8b", "Review")]

        self.assertEqual(client.calls, ["broken:8b", "base:1b"])
        self.assertEqual(events[0]["type"], "warning")
        self.assertEqual(events[-1]["result"].requested_model, "broken:8b")
        self.assertEqual(events[-1]["result"].effective_model, "base:1b")

    async def test_stream_compatibility_retries_transient_reset_on_same_model(self):
        from unittest.mock import AsyncMock, patch
        from web_app.model_compatibility import ModelCompatibilityLayer

        class ErrorStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise ollama.ResponseError("connection was forcibly closed by the remote host", 500)

        class ContentStream:
            def __init__(self):
                self.sent = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.sent:
                    raise StopAsyncIteration
                self.sent = True
                return {"message": {"content": "Recovered on same model."}}

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def list(self):
                return {"models": [
                    {"model": "cold:8b", "digest": "sha256:" + "e" * 64},
                    {"model": "base:1b", "digest": "sha256:" + "f" * 64},
                ]}

            async def chat(self, **request):
                self.calls.append(request["model"])
                return ErrorStream() if len(self.calls) == 1 else ContentStream()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": 1,
                "base_fallback_order": ["base:1b"],
                "models": {},
            }), encoding="utf-8")
            compatibility = ModelCompatibilityLayer.load(policy, root / "state.json")
            client = FakeClient()
            service = OllamaService(client=client)
            service.set_compatibility_layer(compatibility)

            with patch("web_app.ollama_service.asyncio.sleep", new_callable=AsyncMock) as sleep:
                events = [event async for event in service.stream_chat("cold:8b", "Review")]

        self.assertEqual(client.calls, ["cold:8b", "cold:8b"])
        sleep.assert_awaited_once_with(0.5)
        self.assertEqual(events[-1]["result"].effective_model, "cold:8b")


if __name__ == "__main__":
    unittest.main()
