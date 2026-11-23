import io
import json
import asyncio
import threading
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


class _BlockingStreamResponse:
    def __init__(self) -> None:
        self.first_line_read = threading.Event()
        self.release_second_line = threading.Event()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    def __iter__(self):
        yield json.dumps({"message": {"content": "first content"}, "done": False}).encode() + b"\n"
        self.first_line_read.set()
        self.release_second_line.wait(timeout=2)
        yield json.dumps({"message": {"content": " second"}, "done": False}).encode() + b"\n"
        yield json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n"


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

    async def test_stream_chat_yields_first_delta_before_second_line_is_available(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        response = _BlockingStreamResponse()
        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", return_value=response):
            stream = transport.stream_chat("qwen3:4b", "Explain")
            first_event = asyncio.create_task(anext(stream))
            first_line_seen = await asyncio.to_thread(response.first_line_read.wait, 1)
            self.assertTrue(first_line_seen)
            try:
                completed, _pending = await asyncio.wait({first_event}, timeout=0.5)
                self.assertIn(first_event, completed, "first event remained buffered behind the second line")
                self.assertEqual((await first_event)["text"], "first c")
            finally:
                response.release_second_line.set()
                if not first_event.done():
                    await first_event
                await stream.aclose()

        self.assertTrue(response.closed)

    async def test_generate_preserves_messages_controls_and_event_provenance(self):
        from web_app.core.native_ollama import NativeOllamaTransport
        from web_app.inference.protocol import (
            CancellationMetadata,
            ContentPart,
            InferenceMessage,
            InferenceRequest,
        )

        captured = {}
        body = b"".join([
            json.dumps({"message": {"content": "answer"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ])

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data)
            return _Response(body)

        request = InferenceRequest(
            model="qwen3:4b",
            messages=(
                InferenceMessage(role="system", content=(ContentPart(type="text", text="Be exact."),)),
                InferenceMessage(role="user", content=(ContentPart(type="text", text="Answer."),)),
            ),
            temperature=0.1,
            top_p=0.8,
            max_output_tokens=64,
            stop=("END",),
            seed=11,
            cancellation=CancellationMetadata(token="cancel-1"),
        )
        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            events = [event async for event in transport.generate(request)]

        self.assertEqual(captured["payload"]["messages"], [
            {"role": "system", "content": "Be exact."},
            {"role": "user", "content": "Answer."},
        ])
        self.assertEqual(captured["payload"]["options"], {
            "temperature": 0.1,
            "top_p": 0.8,
            "num_predict": 64,
            "stop": ["END"],
            "seed": 11,
        })
        self.assertEqual([event.type for event in events], ["content", "completed"])
        self.assertTrue(all(event.requested_model == "qwen3:4b" for event in events))
        self.assertTrue(all(event.effective_model == "qwen3:4b" for event in events))
        self.assertTrue(all(event.cancellation_token == "cancel-1" for event in events))

    async def test_stream_timeout_preserves_model_timeout_error(self):
        from web_app.core.native_ollama import NativeOllamaTransport
        from web_app.ollama_service import ModelTimeoutError

        class TimeoutResponse(_Response):
            def __iter__(self):
                raise TimeoutError("read timed out")

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", return_value=TimeoutResponse(b"")):
            with self.assertRaises(ModelTimeoutError):
                _events = [event async for event in transport.stream_chat("qwen3:4b", "Explain")]

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
