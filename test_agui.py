import json
import tempfile
import unittest
from pathlib import Path

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from test_support import authenticated_client

from web_app.agui import build_prompt, stream_events
from web_app.app import create_app
from web_app.ollama_service import ModelTimeoutError
from web_app.workspace import WorkspaceService


def _run_input(messages=None, **extra):
    return RunAgentInput.model_validate({
        "threadId": "thread-1",
        "runId": "run-1",
        "messages": messages or [{"id": "message-1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        **extra,
    })


class FakeBackend:
    def __init__(self, events=None, error=None):
        self.events = events or [{"type": "content", "text": "Hello from AG-UI"}]
        self.error = error
        self.calls = []

    async def stream_chat(self, model, prompt):
        self.calls.append((model, prompt))
        if self.error:
            raise self.error
        for event in self.events:
            yield event


def _decode_events(chunks):
    return [
        json.loads(line.removeprefix("data: "))
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: ")
    ]


class AGUIEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_agui_lifecycle_and_text_events(self):
        request = _run_input()
        backend = FakeBackend()
        encoder = EventEncoder(accept="text/event-stream")

        chunks = [
            chunk async for chunk in stream_events(
                request,
                model="qwen2.5-coder:7b",
                prompt=build_prompt(request),
                backend=backend,
                encoder=encoder,
            )
        ]

        events = _decode_events(chunks)
        self.assertEqual(
            [event["type"] for event in events],
            [
                "RUN_STARTED",
                "TEXT_MESSAGE_START",
                "TEXT_MESSAGE_CONTENT",
                "TEXT_MESSAGE_END",
                "RUN_FINISHED",
            ],
        )
        self.assertEqual(events[0]["protocolVersion"], "1.0")
        self.assertEqual(events[2]["delta"], "Hello from AG-UI")
        self.assertEqual(backend.calls, [("qwen2.5-coder:7b", "USER:\nHello")])

    async def test_stream_reports_model_errors_using_agui_run_error(self):
        request = _run_input()
        chunks = [
            chunk async for chunk in stream_events(
                request,
                model="missing",
                prompt=build_prompt(request),
                backend=FakeBackend(error=ModelTimeoutError("Model request timed out")),
                encoder=EventEncoder(accept="text/event-stream"),
            )
        ]

        events = _decode_events(chunks)
        self.assertEqual(events[-1]["type"], "RUN_ERROR")
        self.assertEqual(events[-1]["code"], "model_timeout")

    def test_prompt_rejects_non_text_content_and_unbounded_history(self):
        image_request = _run_input(messages=[{
            "id": "message-1",
            "role": "user",
            "content": [{
                "type": "image",
                "source": {"type": "url", "value": "https://example.test/image.png"},
            }],
        }])
        with self.assertRaisesRegex(ValueError, "text messages only"):
            build_prompt(image_request)

        too_many_messages = _run_input(messages=[
            {"id": f"message-{index}", "role": "user", "content": "x"}
            for index in range(51)
        ])
        with self.assertRaisesRegex(ValueError, "50-message limit"):
            build_prompt(too_many_messages)

    def test_http_endpoint_streams_agui_events_using_forwarded_model(self):
        class FakeService:
            config = {}

            async def stream_chat(self, model, prompt):
                self.last_call = (model, prompt)
                yield {"type": "content", "text": "Connected"}

        with tempfile.TemporaryDirectory() as directory:
            service = FakeService()
            app = create_app(service, workspace=WorkspaceService(Path(directory)))
            with authenticated_client(app) as client:
                response = client.post(
                    "/api/ag-ui/run",
                    headers={"accept": "text/event-stream"},
                    json={
                        "threadId": "thread-1",
                        "runId": "run-1",
                        "messages": [{"id": "message-1", "role": "user", "content": "Hello"}],
                        "tools": [],
                        "context": [],
                        "forwardedProps": {"model": "qwen2.5-coder:7b"},
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual([event["type"] for event in _decode_events(response.text.split("\n\n"))], [
            "RUN_STARTED",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "RUN_FINISHED",
        ])
        self.assertEqual(service.last_call, ("qwen2.5-coder:7b", "USER:\nHello"))


if __name__ == "__main__":
    unittest.main()
