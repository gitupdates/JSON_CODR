import asyncio
import json
import unittest

from web_app.models import GpuProfileSettings
from web_app.ollama_service import ModelOutputError, OllamaService


class Response:
    class Message:
        content = json.dumps({"status": "ready", "summary": "Ready", "content": "Done"})

    message = Message()


class ProfileClient:
    def __init__(self, fail_override=False):
        self.calls = []
        self.fail_override = fail_override

    async def list(self):
        return {"models": [{"name": "qwen2.5-coder:0.5b"}]}

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_override and "options" in kwargs:
            raise RuntimeError("GPU allocation failed")
        return Response()


class GpuProfileTests(unittest.TestCase):
    def run_chat(self, profile, fail_override=False):
        client = ProfileClient(fail_override)
        service = OllamaService(client=client, optimization_provider=lambda model: profile)
        result = asyncio.run(service.chat("qwen2.5-coder:0.5b", "Hello"))
        return result, client.calls

    def test_automatic_profile_sends_no_runner_overrides(self):
        _, calls = self.run_chat(GpuProfileSettings(mode="automatic"))

        self.assertNotIn("options", calls[0])

    def test_profiles_map_to_supported_ollama_runner_options(self):
        cases = [
            (GpuProfileSettings(mode="gpu_preferred"), {"num_gpu": 999}),
            (GpuProfileSettings(mode="balanced"), {"num_gpu": 16}),
            (GpuProfileSettings(mode="vram_conservative"), {"num_ctx": 2048, "num_batch": 128}),
            (GpuProfileSettings(mode="cpu_only"), {"num_gpu": 0}),
            (
                GpuProfileSettings(mode="advanced", num_gpu=22, main_gpu=0, num_ctx=4096, num_batch=256),
                {"num_gpu": 22, "main_gpu": 0, "num_ctx": 4096, "num_batch": 256},
            ),
        ]

        for profile, expected in cases:
            with self.subTest(profile=profile.mode):
                _, calls = self.run_chat(profile)
                self.assertEqual(calls[0]["options"], expected)

    def test_failed_override_retries_once_with_automatic_options(self):
        result, calls = self.run_chat(GpuProfileSettings(mode="gpu_preferred"), fail_override=True)

        self.assertEqual(result.status, "ready")
        self.assertEqual(len(calls), 2)
        self.assertIn("options", calls[0])
        self.assertNotIn("options", calls[1])

    def test_plain_text_is_preserved_when_model_ignores_structured_schema(self):
        class PlainResponse:
            class Message:
                content = "Qwen 3.5 received the shared request."

            message = Message()

        class PlainClient(ProfileClient):
            async def chat(self, **kwargs):
                self.calls.append(kwargs)
                return PlainResponse()

        service = OllamaService(client=PlainClient())

        result = asyncio.run(service.chat("qwen2.5-coder:0.5b", "Hello"))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.summary, "Qwen 3.5 received the shared request.")
        self.assertEqual(result.content, "Qwen 3.5 received the shared request.")
        self.assertEqual(result.error, "structured_output_fallback")
        self.assertEqual(result.provider_events[0]["initial_raw"], "Qwen 3.5 received the shared request.")

    def test_malformed_response_gets_one_schema_repair_attempt(self):
        class RepairClient(ProfileClient):
            async def chat(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    class PlainResponse:
                        class Message:
                            content = "I received the request."
                        message = Message()
                    return PlainResponse()
                return Response()

        client = RepairClient()
        service = OllamaService(client=client)

        result = asyncio.run(service.chat("qwen2.5-coder:0.5b", "Hello"))

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.summary, "Ready")
        self.assertIsNone(result.error)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result.provider_events[0]["initial_raw"], "I received the request.")
        self.assertIn('"content": "Done"', result.provider_events[0]["repaired_raw"])

    def test_structured_response_with_empty_content_gets_one_repair_attempt(self):
        class EmptyThenReadyClient(ProfileClient):
            async def chat(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    class EmptyResponse:
                        class Message:
                            content = json.dumps({"status": "failed", "summary": "partial", "content": ""})
                        message = Message()
                    return EmptyResponse()
                return Response()

        client = EmptyThenReadyClient()
        service = OllamaService(client=client)

        result = asyncio.run(service.chat("qwen2.5-coder:0.5b", "Hello"))

        self.assertEqual(result.content, "Done")
        self.assertEqual(len(client.calls), 2)
        self.assertIn("Reformat your previous answer", client.calls[1]["messages"][-1]["content"])

    def test_empty_provider_message_gets_one_schema_retry(self):
        class EmptyThenReadyClient(ProfileClient):
            async def chat(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    class EmptyResponse:
                        class Message:
                            content = ""
                        message = Message()
                    return EmptyResponse()
                return Response()

        client = EmptyThenReadyClient()
        service = OllamaService(client=client)

        result = asyncio.run(service.chat("qwen2.5-coder:0.5b", "Hello"))

        self.assertEqual(result.content, "Done")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result.provider_events[0]["initial_raw"], "")

    def test_two_empty_provider_messages_remain_a_hard_failure(self):
        class EmptyClient(ProfileClient):
            async def chat(self, **kwargs):
                self.calls.append(kwargs)
                class EmptyResponse:
                    class Message:
                        content = ""
                    message = Message()
                return EmptyResponse()

        client = EmptyClient()
        service = OllamaService(client=client)

        with self.assertRaisesRegex(ModelOutputError, "Malformed structured output") as caught:
            asyncio.run(service.chat("qwen2.5-coder:0.5b", "Hello"))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(caught.exception.provider_events[0]["type"], "schema_repair")
        self.assertEqual(caught.exception.provider_events[0]["initial_raw"], "")
        self.assertEqual(caught.exception.provider_events[0]["repaired_raw"], "")

    def test_archive_conversion_uses_the_selected_profile(self):
        class ConversionClient(ProfileClient):
            async def chat(self, **kwargs):
                self.calls.append(kwargs)
                class ConversionResponse:
                    class Message:
                        content = json.dumps({
                            "summary": "Converted",
                            "files": [{"path": "README.md", "content": "Ready"}],
                        })
                    message = Message()
                return ConversionResponse()

        client = ConversionClient()
        service = OllamaService(
            client=client,
            optimization_provider=lambda model: GpuProfileSettings(mode="gpu_preferred"),
        )

        asyncio.run(service.convert_archive("qwen2.5-coder:0.5b", "Convert"))

        self.assertEqual(client.calls[0]["options"], {"num_gpu": 999})


if __name__ == "__main__":
    unittest.main()
