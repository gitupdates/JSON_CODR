import asyncio
import json
import unittest

from web_app.models import GpuProfileSettings
from web_app.ollama_service import OllamaService


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


if __name__ == "__main__":
    unittest.main()
