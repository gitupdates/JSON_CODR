import json
import os
import unittest

from web_app.core.agent_services import planner_output_schema
from web_app.core.native_ollama import NativeOllamaTransport


@unittest.skipUnless(os.environ.get("JSON_CODR_RUN_MODEL_CONFORMANCE") == "1", "real model probe is opt-in")
class InstalledQwenConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_qwen_7b_obeys_exact_coding_envelope_without_authority(self):
        model = "qwen2.5-coder:7b-instruct-q4_K_M"
        transport = NativeOllamaTransport("http://127.0.0.1:11434", timeout_seconds=180)
        installed = {item.get("name") or item.get("model"): item for item in await transport.list_models()}
        self.assertIn(model, installed)
        schema = planner_output_schema(("project.read", "project.patch", "test.run"))
        prompts = (
            "Return the exact JSON envelope for reading app.py. No prose. You have no credentials or network authority.",
            "Return the exact JSON envelope for patching app.py with arguments containing patch text. No prose.",
            "Return the exact JSON envelope with done true after persisted evidence exists. No prose.",
        )
        outputs = [json.loads(await transport.json_chat(model, prompt, schema)) for prompt in prompts]
        required = {"done", "capability_id", "operation", "target_path", "arguments"}
        self.assertTrue(all(set(output) == required for output in outputs))
        self.assertIn(outputs[0]["capability_id"], {"project.read", "project.patch", "test.run"})
        self.assertTrue(outputs[-1]["done"])


if __name__ == "__main__":
    unittest.main()
