import io
import json
import asyncio
import threading
import unittest
from urllib.error import HTTPError
from unittest.mock import AsyncMock, patch


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


class ModelPolicyTests(unittest.TestCase):
    _PREFERRED_DIGEST = "sha256:" + "a" * 64
    _FALLBACK_DIGEST = "sha256:" + "b" * 64

    def _policy(self):
        from web_app.core.model_policy import ModelPolicy

        return ModelPolicy.from_document({
            "schema_version": "2",
            "policy_version": "2026-11-24.99",
            "probe": {
                "prompt": "Return only JSON_CODR_MODEL_PROBE_OK",
                "expected": "JSON_CODR_MODEL_PROBE_OK",
                "timeout_seconds": 5,
                "maximum_tokens": 16,
            },
            "models": [
                {
                    "name": "preferred-code:1b",
                    "digest": self._PREFERRED_DIGEST,
                    "purpose": "reviewed local coding",
                    "maximum_download_bytes": 100,
                },
                {
                    "name": "fallback-code:0.5b",
                    "digest": self._FALLBACK_DIGEST,
                    "purpose": "reviewed local coding",
                    "maximum_download_bytes": 50,
                },
            ],
        })

    def test_missing_preferred_model_selects_reviewed_fallback(self):
        policy = self._policy()

        evidence = policy.select(
            [{"name": "fallback-code:0.5b", "digest": "b" * 64}],
            probe=lambda _model, _probe: True,
        )

        self.assertEqual(evidence.model, "fallback-code:0.5b")
        self.assertEqual(evidence.digest, self._FALLBACK_DIGEST)
        self.assertIn("preferred-code:1b is not installed", evidence.fallback_reason)

    def test_mutable_tag_digest_drift_is_rejected(self):
        from web_app.core.model_policy import ModelPolicyError

        policy = self._policy()
        with self.assertRaisesRegex(ModelPolicyError, "digest"):
            policy.select(
                [{"name": "preferred-code:1b", "digest": "c" * 64}],
                probe=lambda _model, _probe: True,
            )

    def test_failed_coding_probe_is_rejected(self):
        from web_app.core.model_policy import ModelPolicyError

        policy = self._policy()
        with self.assertRaisesRegex(ModelPolicyError, "probe"):
            policy.select(
                [{"name": "preferred-code:1b", "digest": "a" * 64}],
                probe=lambda _model, _probe: False,
            )

    def test_valid_fallback_records_policy_digest_probe_and_reason(self):
        policy = self._policy()

        evidence = policy.select(
            [
                {"name": "preferred-code:1b", "digest": "c" * 64},
                {"name": "fallback-code:0.5b", "digest": "b" * 64},
            ],
            probe=lambda model, _probe: model == "fallback-code:0.5b",
        )

        self.assertEqual(evidence.policy_version, "2026-11-24.99")
        self.assertEqual(evidence.model, "fallback-code:0.5b")
        self.assertEqual(evidence.digest, self._FALLBACK_DIGEST)
        self.assertTrue(evidence.probe_passed)
        self.assertIn("digest drift", evidence.fallback_reason)

    def test_local_policy_recovers_from_transient_inventory_connection_reset(self):
        from web_app.core.model_policy import evaluate_local_policy

        policy = self._policy()
        responses = [
            ConnectionResetError("daemon recycled the inventory connection"),
            _Response(json.dumps({
                "models": [{"name": "preferred-code:1b", "digest": "a" * 64}]
            }).encode()),
            _Response(json.dumps({
                "response": json.dumps({"status": "JSON_CODR_MODEL_PROBE_OK"})
            }).encode()),
        ]

        with (
            patch("web_app.core.model_policy.urlopen", side_effect=responses),
            patch("web_app.core.model_policy.time.sleep") as sleep,
        ):
            evidence = evaluate_local_policy(policy, "http://127.0.0.1:11434")

        self.assertEqual(evidence.model, "preferred-code:1b")
        sleep.assert_called_once_with(0.5)


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

    async def test_reviewed_model_digest_drift_is_rejected_before_inference(self):
        from web_app.core.model_policy import ModelPolicy, ModelPolicyError
        from web_app.core.native_ollama import NativeOllamaTransport

        expected = "sha256:" + "a" * 64
        policy = ModelPolicy.from_document({
            "schema_version": "2",
            "policy_version": "2026-11-24.99",
            "probe": {
                "prompt": "Return JSON status",
                "expected": "JSON_CODR_MODEL_PROBE_OK",
                "timeout_seconds": 5,
                "maximum_tokens": 16,
            },
            "models": [
                {
                    "name": "reviewed-code:1b",
                    "digest": expected,
                    "purpose": "reviewed local coding",
                    "maximum_download_bytes": 100,
                },
                {
                    "name": "fallback-code:0.5b",
                    "digest": "sha256:" + "b" * 64,
                    "purpose": "reviewed local coding",
                    "maximum_download_bytes": 50,
                },
            ],
        })
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, request.method, timeout))
            return _Response(json.dumps({
                "models": [{"name": "reviewed-code:1b", "digest": "c" * 64}]
            }).encode())

        transport = NativeOllamaTransport(
            "http://127.0.0.1:11434", timeout_seconds=17, model_policy=policy
        )
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(ModelPolicyError, "digest drift"):
                _ = [event async for event in transport.stream_chat("reviewed-code:1b", "code")]

        self.assertEqual(calls, [("http://127.0.0.1:11434/api/tags", "GET", 17)])

    async def test_model_discovery_recovers_from_a_transient_connection_reset(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls == 1:
                raise ConnectionResetError("daemon recycled the local connection")
            return _Response(json.dumps({"models": [{"name": "deepcoder:1.5b"}]}).encode())

        transport = NativeOllamaTransport("http://127.0.0.1:11434")
        with (
            patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen),
            patch("web_app.core.native_ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            models = await transport.list_models()

        self.assertEqual(models, [{"name": "deepcoder:1.5b"}])
        self.assertEqual(calls, 2)
        sleep.assert_awaited_once_with(0.25)

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
        self.assertEqual(captured["payload"]["options"], {
            "num_ctx": 8192,
            "num_predict": 512,
            "temperature": 0.0,
        })
        self.assertEqual(events[0]["type"], "reasoning")
        self.assertEqual("".join(event["text"] for event in events if event["type"] == "content"), "Verified answer.")
        self.assertEqual(events[-1]["type"], "completed")
        self.assertEqual(events[-1]["result"].model, "qwen3:4b")
        self.assertEqual(events[-1]["result"].content, "Verified answer.")

    async def test_stream_chat_retries_without_thinking_when_reasoning_exhausts_budget(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        payloads = []
        responses = [
            _Response(b"".join([
                json.dumps({"message": {"thinking": "Long rationale.", "content": ""}, "done": False}).encode() + b"\n",
                json.dumps({"message": {"thinking": "", "content": ""}, "done": True}).encode() + b"\n",
            ])),
            _Response(b"".join([
                json.dumps({"message": {"content": "Recovered answer."}, "done": False}).encode() + b"\n",
                json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
            ])),
        ]

        def fake_urlopen(request, timeout):
            del timeout
            payloads.append(json.loads(request.data))
            return responses.pop(0)

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            events = [event async for event in transport.stream_chat(
                "qwen3:4b", "Reply", public_reasoning=True,
            )]

        self.assertEqual([payload["think"] for payload in payloads], [True, False])
        self.assertEqual(payloads[1]["messages"], [{"role": "user", "content": "Reply"}])
        self.assertEqual(events[-1]["result"].content, "Recovered answer.")
        self.assertEqual(events[-1]["result"].reasoning.entries[0].text, "Long rationale.")
        self.assertTrue(any(
            "final-answer mode" in warning
            for warning in events[-1]["result"].reasoning.warnings
        ))

    async def test_stream_chat_retries_with_thinking_disabled_for_incompatible_model(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        payloads = []
        responses = [
            _Response(json.dumps({
                "error": '"qwen2.5-coder:0.5b" does not support thinking',
            }).encode() + b"\n"),
            _Response(b"".join([
                json.dumps({"message": {"content": "Recovered answer."}, "done": False}).encode()
                + b"\n",
                json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
            ])),
        ]

        def fake_urlopen(request, timeout):
            del timeout
            payloads.append(json.loads(request.data))
            return responses.pop(0)

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            events = [event async for event in transport.stream_chat(
                "qwen2.5-coder:0.5b", "Reply", public_reasoning=True,
            )]

        self.assertEqual([payload["think"] for payload in payloads], [True, False])
        self.assertEqual(payloads[1]["messages"], [{"role": "user", "content": "Reply"}])
        self.assertEqual(events[-1]["result"].content, "Recovered answer.")
        self.assertTrue(any(
            "thinking disabled" in warning
            for warning in events[-1]["result"].reasoning.warnings
        ))

    async def test_stream_chat_retries_without_thinking_when_runner_resets_after_reasoning(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        payloads = []
        responses = [
            _Response(b"".join([
                json.dumps({"message": {"thinking": "Partial rationale.", "content": ""}, "done": False}).encode() + b"\n",
                json.dumps({
                    "error": "an error was encountered while running the model: "
                    "wsarecv: An existing connection was forcibly closed by the remote host."
                }).encode() + b"\n",
            ])),
            _Response(b"".join([
                json.dumps({"message": {"content": "Recovered after reset."}, "done": False}).encode() + b"\n",
                json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
            ])),
        ]

        def fake_urlopen(request, timeout):
            del timeout
            payloads.append(json.loads(request.data))
            return responses.pop(0)

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            events = [event async for event in transport.stream_chat(
                "qwen3:4b", "Reply", public_reasoning=True,
            )]

        self.assertEqual([payload["think"] for payload in payloads], [True, False])
        self.assertEqual(events[-1]["result"].content, "Recovered after reset.")
        self.assertEqual(events[-1]["result"].reasoning.entries[0].text, "Partial rationale.")

    async def test_stream_chat_disables_thinking_and_bounds_default_generation(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        captured = {}
        body = b"".join([
            json.dumps({"message": {"content": "OK"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ])

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data)
            return _Response(body)

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            events = [event async for event in transport.stream_chat("qwen3:4b", "Reply with OK")]

        self.assertFalse(captured["payload"]["think"])
        self.assertEqual(captured["payload"]["keep_alive"], "5m")
        self.assertEqual(captured["payload"]["options"], {
            "num_ctx": 2048,
            "num_predict": 512,
            "temperature": 0.0,
        })
        self.assertEqual(events[-1]["result"].content, "OK")

    async def test_stream_chat_treats_done_chunk_as_success_before_socket_teardown(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        class DoneThenResetResponse(_Response):
            def __iter__(self):
                yield json.dumps({
                    "message": {"content": "Complete answer."}, "done": False,
                }).encode() + b"\n"
                yield json.dumps({
                    "message": {"content": ""}, "done": True,
                }).encode() + b"\n"
                raise ConnectionResetError("socket closed after done")

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch(
            "web_app.core.native_ollama.urlopen",
            return_value=DoneThenResetResponse(b""),
        ):
            events = [event async for event in transport.stream_chat("qwen2.5-coder:3b", "Reply")]

        result = events[-1]["result"]
        self.assertEqual(result.content, "Complete answer.")
        self.assertIsNone(result.reasoning)

    async def test_stream_chat_retries_cold_runner_resets_before_the_first_delta(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0
        body = b"".join([
            json.dumps({"message": {"content": "OK"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ])

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls <= 2:
                raise ConnectionResetError("runner still loading")
            return _Response(body)

        transport = NativeOllamaTransport("http://localhost:11434")
        with (
            patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen),
            patch("web_app.core.native_ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            events = [event async for event in transport.stream_chat("deepcoder:1.5b", "Reply")]

        self.assertEqual(calls, 3)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [0.5, 1.0])
        self.assertEqual(events[-1]["result"].content, "OK")

    async def test_stream_chat_retries_an_empty_cold_runner_http_500(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0
        body = b"".join([
            json.dumps({"message": {"content": "OK"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ])

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls == 1:
                raise HTTPError(
                    "http://localhost:11434/api/chat",
                    500,
                    "Internal Server Error",
                    {},
                    io.BytesIO(b""),
                )
            return _Response(body)

        transport = NativeOllamaTransport("http://localhost:11434")
        with (
            patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen),
            patch("web_app.core.native_ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            events = [event async for event in transport.stream_chat("qwen2.5-coder:3b", "Reply")]

        self.assertEqual(calls, 2)
        sleep.assert_awaited_once_with(0.5)
        self.assertEqual(events[-1]["result"].content, "OK")

    async def test_stream_chat_retries_detailed_tokenizer_connection_failure(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0
        body = b"".join([
            json.dumps({"message": {"content": "Recovered"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ])

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls == 1:
                raise HTTPError(
                    "http://localhost:11434/api/chat",
                    500,
                    "Internal Server Error",
                    {},
                    io.BytesIO(json.dumps({
                        "error": 'Post "http://127.0.0.1:65000/tokenize": '
                        "connectex: A connection attempt failed because the connected party "
                        "did not properly respond after a period of time."
                    }).encode()),
                )
            return _Response(body)

        transport = NativeOllamaTransport("http://localhost:11434")
        with (
            patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen),
            patch("web_app.core.native_ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            events = [event async for event in transport.stream_chat("deepseek-coder:6.7b", "Reply")]

        self.assertEqual(calls, 2)
        sleep.assert_awaited_once_with(0.5)
        self.assertEqual(events[-1]["result"].content, "Recovered")

    async def test_stream_chat_keeps_partial_content_when_runner_resets_after_generation(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        class ContentThenResetResponse(_Response):
            def __iter__(self):
                yield json.dumps({
                    "message": {"content": "Usable answer."}, "done": False,
                }).encode() + b"\n"
                raise ConnectionResetError("runner reset after generation")

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch(
            "web_app.core.native_ollama.urlopen",
            return_value=ContentThenResetResponse(b""),
        ):
            events = [event async for event in transport.stream_chat("deepcoder:1.5b", "Reply")]

        result = events[-1]["result"]
        self.assertEqual(result.content, "Usable answer.")
        self.assertTrue(any("runner reset" in warning for warning in result.reasoning.warnings))

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
        self.assertEqual(captured["payload"]["keep_alive"], "5m")
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
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data)
            return _Response(
                json.dumps({"message": {"content": '{"done":true}'}, "done": True}).encode() + b"\n"
            )

        transport = NativeOllamaTransport("http://localhost:11434")
        schema = {"type": "object", "properties": {"done": {"type": "boolean"}}}
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            content = await transport.json_chat("qwen3:4b", "Plan", schema)

        self.assertEqual(content, '{"done":true}')
        self.assertEqual(captured["url"], "http://localhost:11434/api/chat")
        self.assertEqual(captured["payload"]["format"], "json")
        self.assertIn(
            json.dumps(schema, sort_keys=True, separators=(",", ":")),
            captured["payload"]["messages"][0]["content"],
        )
        self.assertTrue(captured["payload"]["stream"])
        self.assertNotIn("raw", captured["payload"])
        self.assertFalse(captured["payload"]["think"])
        self.assertEqual(captured["payload"]["keep_alive"], "5m")
        self.assertEqual(captured["payload"]["options"], {
            "temperature": 0.0,
            "num_ctx": 2048,
            "num_predict": 512,
        })

    async def test_json_chat_retries_one_plain_connection_reset(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        captured = []

        def fake_urlopen(request, timeout):
            captured.append(json.loads(request.data))
            if len(captured) == 1:
                raise ConnectionResetError("runner reset")
            return _Response(
                json.dumps({"message": {"content": '{"done":false}'}, "done": True}).encode() + b"\n"
            )

        transport = NativeOllamaTransport("http://localhost:11434")
        schema = {"type": "object", "properties": {"done": {"type": "boolean"}}}
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            result = await transport.json_chat("qwen3:4b", "Plan", schema)

        self.assertEqual(result, '{"done":false}')
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["format"], "json")

    async def test_json_chat_retries_runner_restart_reported_inside_successful_http_stream(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls == 1:
                return _Response(json.dumps({
                    "error": "an error was encountered while running the model: "
                    "wsarecv: An existing connection was forcibly closed by the remote host."
                }).encode() + b"\n")
            return _Response(
                json.dumps({"message": {"content": '{"done":true}'}, "done": True}).encode()
                + b"\n"
            )

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            try:
                result = await transport.json_chat("qwen3:4b", "Plan", {"type": "object"})
            except Exception as error:
                self.fail(f"transport rejected a recoverable in-stream runner restart: {error}")

        self.assertEqual(result, '{"done":true}')
        self.assertEqual(calls, 2)

    async def test_json_chat_recovers_from_two_consecutive_runner_restarts(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls <= 2:
                raise ConnectionResetError("runner reset")
            return _Response(
                json.dumps({"message": {"content": '{"done":true}'}, "done": True}).encode()
                + b"\n"
            )

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            result = await transport.json_chat("qwen3:4b", "Plan", {"type": "object"})

        self.assertEqual(result, '{"done":true}')
        self.assertEqual(calls, 3)

    async def test_json_chat_waits_for_a_cold_runner_after_four_consecutive_resets(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls <= 4:
                raise ConnectionResetError("runner still loading")
            return _Response(
                json.dumps({"message": {"content": '{"done":true}'}, "done": True}).encode()
                + b"\n"
            )

        transport = NativeOllamaTransport("http://localhost:11434")
        with (
            patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen),
            patch("web_app.core.native_ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            result = await transport.json_chat("deepcoder:1.5b", "Plan", {"type": "object"})

        self.assertEqual(result, '{"done":true}')
        self.assertEqual(calls, 5)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [0.5, 1.0, 2.0, 4.0])

    async def test_json_chat_keeps_complete_streamed_object_when_runner_resets_after_generation(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        class CompleteThenResetResponse(_Response):
            def __iter__(self):
                yield json.dumps({
                    "message": {"content": '{"done":false}'}, "done": False,
                }).encode() + b"\n"
                raise ConnectionResetError("runner reset after generation")

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch(
            "web_app.core.native_ollama.urlopen",
            return_value=CompleteThenResetResponse(b""),
        ):
            result = await transport.json_chat(
                "qwen3:4b", "Plan", {"type": "object", "properties": {"done": {"type": "boolean"}}}
            )

        self.assertEqual(result, '{"done":false}')

    async def test_json_chat_preserves_local_ollama_http_error_detail(self):
        from web_app.core.native_ollama import NativeOllamaTransport
        from web_app.ollama_service import OllamaUnavailableError

        def fake_urlopen(_request, timeout):
            del timeout
            raise HTTPError(
                "http://localhost:11434/api/chat",
                500,
                "Internal Server Error",
                {},
                io.BytesIO(b'{"error":"model runner stopped"}'),
            )

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(OllamaUnavailableError, "model runner stopped"):
                await transport.json_chat("qwen3:4b", "Plan", {"type": "object"})

    async def test_json_chat_retries_one_transient_tokenizer_runner_restart(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls == 1:
                raise HTTPError(
                    "http://localhost:11434/api/chat",
                    500,
                    "Internal Server Error",
                    {},
                    io.BytesIO(json.dumps({
                        "error": 'Post "http://127.0.0.1:65000/tokenize": '
                        "wsarecv: An existing connection was forcibly closed by the remote host."
                    }).encode()),
                )
            return _Response(json.dumps({"message": {"content": '{"done":false}'}}).encode())

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            result = await transport.json_chat("qwen3:4b", "Plan", {"type": "object"})

        self.assertEqual(result, '{"done":false}')
        self.assertEqual(calls, 2)

    async def test_json_chat_retries_one_transient_model_runner_restart(self):
        from web_app.core.native_ollama import NativeOllamaTransport

        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            del timeout
            calls += 1
            if calls == 1:
                raise HTTPError(
                    "http://localhost:11434/api/chat",
                    500,
                    "Internal Server Error",
                    {},
                    io.BytesIO(json.dumps({
                        "error": "an error was encountered while running the model: "
                        "wsarecv: An existing connection was forcibly closed by the remote host."
                    }).encode()),
                )
            return _Response(json.dumps({"message": {"content": '{"done":false}'}}).encode())

        transport = NativeOllamaTransport("http://localhost:11434")
        with patch("web_app.core.native_ollama.urlopen", side_effect=fake_urlopen):
            result = await transport.json_chat("qwen3:4b", "Plan", {"type": "object"})

        self.assertEqual(result, '{"done":false}')
        self.assertEqual(calls, 2)

    async def test_compatibility_falls_back_before_output_and_reports_effective_model(self):
        from pathlib import Path
        import tempfile
        from web_app.core.native_ollama import NativeOllamaTransport
        from web_app.model_compatibility import ModelCompatibilityLayer

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": 1,
                "base_fallback_order": ["base-coder:1b"],
                "models": {},
            }), encoding="utf-8")
            layer = ModelCompatibilityLayer.load(policy, root / "state.json")

            class CompatibleTransport(NativeOllamaTransport):
                def __init__(self):
                    super().__init__("http://localhost:11434", compatibility=layer)
                    self.calls = []

                async def list_models(self):
                    return [
                        {"name": "broken:8b", "digest": "sha256:" + "5" * 64},
                        {"name": "base-coder:1b", "digest": "sha256:" + "6" * 64},
                    ]

                async def _stream_request(self, _path, payload):
                    self.calls.append(payload["model"])
                    if payload["model"] == "broken:8b":
                        yield json.dumps({"error": "llama-server process has terminated"}).encode()
                    else:
                        yield json.dumps({"message": {"content": "fallback answer"}, "done": False}).encode()
                        yield json.dumps({"message": {"content": ""}, "done": True}).encode()

            transport = CompatibleTransport()
            events = [event async for event in transport.stream_chat("broken:8b", "hello")]

            self.assertEqual(transport.calls, ["broken:8b", "base-coder:1b"])
            self.assertEqual(events[0]["type"], "warning")
            self.assertEqual(events[-1]["result"].model, "base-coder:1b")
            self.assertEqual(events[-1]["result"].requested_model, "broken:8b")
            self.assertEqual(events[-1]["result"].effective_model, "base-coder:1b")
            fallback = events[-1]["result"].provider_events[0]
            self.assertEqual(fallback["requested_model"], "broken:8b")
            self.assertEqual(fallback["effective_model"], "base-coder:1b")

    async def test_compatibility_never_substitutes_after_partial_stream_output(self):
        from pathlib import Path
        import tempfile
        from web_app.core.native_ollama import NativeOllamaTransport
        from web_app.model_compatibility import ModelCompatibilityLayer
        from web_app.ollama_service import OllamaUnavailableError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": 1,
                "base_fallback_order": ["base-coder:1b"],
                "models": {},
            }), encoding="utf-8")
            layer = ModelCompatibilityLayer.load(policy, root / "state.json")

            class PartialTransport(NativeOllamaTransport):
                def __init__(self):
                    super().__init__("http://localhost:11434", compatibility=layer)
                    self.calls = []

                async def list_models(self):
                    return [
                        {"name": "partial:8b", "digest": "sha256:" + "7" * 64},
                        {"name": "base-coder:1b", "digest": "sha256:" + "8" * 64},
                    ]

                async def _stream_request(self, _path, payload):
                    self.calls.append(payload["model"])
                    yield json.dumps({"message": {"content": "partial"}, "done": False}).encode()
                    yield json.dumps({"error": "llama-server process has terminated"}).encode()

            transport = PartialTransport()
            events = []
            with self.assertRaises(OllamaUnavailableError):
                async for event in transport.stream_chat("partial:8b", "hello"):
                    events.append(event)

            self.assertEqual(transport.calls, ["partial:8b"])
            self.assertEqual([event["type"] for event in events], ["content"])
            self.assertTrue(events[0]["text"])

if __name__ == "__main__":
    unittest.main()
