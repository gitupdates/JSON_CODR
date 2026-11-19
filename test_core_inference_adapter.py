import unittest
import warnings

from web_app.core.adapters import CapabilityCall, ExecutionContext
from web_app.core.inference_adapter import InferenceAdapter
from web_app.models import ChatResult


class RecordingBackend:
    def __init__(self) -> None:
        self.prompt = None

    async def chat(self, model, prompt, images):
        self.prompt = prompt
        return ChatResult(model=model, status="success", summary="ok", content="ok")


class StreamingBackend:
    async def stream_chat(self, model, prompt, images, public_reasoning=False):
        yield {"type": "reasoning", "text": "Inspect evidence.", "provenance": "native_provider"}
        yield {"type": "content", "text": "Live "}
        yield {"type": "content", "text": "answer"}
        yield {
            "type": "completed",
            "result": ChatResult(model=model, status="success", summary="done", content="Live answer"),
        }


class FailingStreamingBackend:
    async def stream_chat(self, model, prompt, images, public_reasoning=False):
        yield {"type": "content", "text": "partial"}
        raise RuntimeError("provider disconnected")


class ResolvingStreamingBackend(StreamingBackend):
    async def list_models(self):
        return [{"name": "qwen3:4b"}]


class InferenceAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_context_is_injected_and_reported_in_result(self):
        backend = RecordingBackend()

        def prepare_prompt(call, prompt):
            self.assertEqual(call.arguments["session_id"], "a" * 32)
            return (
                f"ATTACHED SKILL rea-agents:reverse-engineer-anything\n{prompt}",
                {
                    "attached_skills": [{
                        "reference": "rea-agents:reverse-engineer-anything",
                        "name": "Reverse engineer anything (REA)",
                        "score": 11,
                        "reasons": ["skillset: planning"],
                        "manual": False,
                    }],
                    "attached_skillsets": ["planning"],
                    "skill_recommendations": [],
                },
            )

        adapter = InferenceAdapter(backend, prepare_prompt=prepare_prompt)
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={
                "model": "granite-code:8b-instruct",
                "prompt": "Plan a reverse-engineering workflow",
                "session_id": "a" * 32,
            },
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            events = [event async for event in adapter.execute(call, context)]

        self.assertIn("ATTACHED SKILL rea-agents:reverse-engineer-anything", backend.prompt)
        result = events[0].payload["result"]
        self.assertEqual(result["attached_skillsets"], ["planning"])
        self.assertEqual(result["attached_skills"][0]["reference"], "rea-agents:reverse-engineer-anything")
        self.assertEqual(caught, [])

    async def test_streaming_backend_emits_real_reasoning_and_content_before_completion(self):
        adapter = InferenceAdapter(StreamingBackend())
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={"model": "qwen", "prompt": "Explain", "public_reasoning": True},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        events = [event async for event in adapter.execute(call, context)]

        self.assertEqual(
            [event.event_type for event in events],
            ["inference.reasoning.delta", "inference.content.delta", "inference.content.delta", "inference.completed"],
        )
        self.assertEqual(events[0].payload["provenance"], "native_provider")
        self.assertEqual(events[-1].payload["result"]["content"], "Live answer")

    async def test_partial_stream_is_not_converted_into_a_false_completion(self):
        adapter = InferenceAdapter(FailingStreamingBackend())
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={"model": "qwen", "prompt": "Explain"},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        events = []
        with self.assertRaisesRegex(RuntimeError, "provider disconnected"):
            async for event in adapter.execute(call, context):
                events.append(event)

        self.assertEqual([event.event_type for event in events], ["inference.content.delta"])

    async def test_model_tag_resolution_reports_requested_and_effective_identity(self):
        from web_app.core.model_tags import ModelTag, ModelTagRegistry

        registry = ModelTagRegistry({"coding": ModelTag(("missing:70b", "qwen3:4b"), ())}, ("qwen3:4b",))
        adapter = InferenceAdapter(ResolvingStreamingBackend(), model_registry=registry)
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={"model": "coding", "prompt": "Explain"},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        events = [event async for event in adapter.execute(call, context)]

        completed = events[-1].payload
        self.assertEqual(completed["requested_model_id"], "coding")
        self.assertEqual(completed["effective_model_id"], "qwen3:4b")
        self.assertTrue(completed["fallback_used"])


if __name__ == "__main__":
    unittest.main()
