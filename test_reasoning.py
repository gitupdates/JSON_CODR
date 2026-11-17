import unittest

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


if __name__ == "__main__":
    unittest.main()
