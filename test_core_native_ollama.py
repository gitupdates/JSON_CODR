import io
import json
import unittest
from unittest.mock import patch


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body.read()

    def __iter__(self):
        return iter(self._body.readlines())


class NativeOllamaTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_non_loopback_endpoint(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        with self.assertRaisesRegex(ValueError, "loopback"):
            NativeOllamaTransport("http://192.168.1.50:11434")

    async def test_health_and_models_use_raw_local_http(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, request.method, timeout))
            return _Response(json.dumps({"models": [{"name": "qwen3:4b"}]}).encode())

        transport = NativeOllamaTransport("http://127.0.0.1:11434", timeout_seconds=17)
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            self.assertEqual(await transport.health(), {"ollama": True})
            self.assertEqual(await transport.list_models(), [{"name": "qwen3:4b"}])

        self.assertEqual(calls, [
            ("http://127.0.0.1:11434/api/tags", "GET", 17),
            ("http://127.0.0.1:11434/api/tags", "GET", 17),
        ])

    async def test_stream_chat_preserves_native_content_and_identity(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        captured = {}
        body = b"".join([
            json.dumps({"message": {"thinking": "Check evidence.\n", "content": ""}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": "Verified answer."}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ])

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return _Response(body)

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            events = [event async for event in transport.stream_chat(
                "qwen3:4b",
                "Explain",
                public_reasoning=True,
                model_options={"num_ctx": 8192, "temperature": 0.0},
            )]

        self.assertEqual(captured["url"], "http://localhost:11434/api/chat")
        self.assertEqual(captured["payload"]["model"], "qwen3:4b")
        self.assertTrue(captured["payload"]["stream"])
        self.assertTrue(captured["payload"]["think"])
        self.assertEqual(captured["payload"]["options"], {"num_ctx": 8192, "temperature": 0.0})
        self.assertEqual(events[0]["type"], "reasoning")
        self.assertEqual("".join(event["text"] for event in events if event["type"] == "content"), "Verified answer.")
        self.assertEqual(events[-1]["type"], "completed")
        self.assertEqual(events[-1]["result"].model, "qwen3:4b")
        self.assertEqual(events[-1]["result"].content, "Verified answer.")

    async def test_json_chat_requests_schema_constrained_local_output(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data)
            return _Response(json.dumps({"message": {"content": '{"done":true}'}}).encode())

        transport = NativeOllamaTransport("http://localhost:11434")
        schema = {"type": "object", "properties": {"done": {"type": "boolean"}}}
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            content = await transport.json_chat("qwen3:4b", "Plan", schema)

        self.assertEqual(content, '{"done":true}')
        self.assertEqual(captured["payload"]["format"], schema)
        self.assertFalse(captured["payload"]["stream"])


if __name__ == "__main__":
    unittest.main()
