import unittest
import warnings

from web_app.core.adapters import CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.inference_adapter import InferenceAdapter
from web_app.models import ChatResult
from web_app.ollama_service import OllamaUnavailableError


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


class CompatibilityResolvingBackend(StreamingBackend):
    def __init__(self):
        self.selected = None

    async def list_models(self):
        return [
            {"name": "broken:8b", "installed": True, "runnable": False},
            {"name": "new:8b", "installed": True, "runnable": None},
        ]

    async def stream_chat(self, model, prompt, images, public_reasoning=False):
        self.selected = model
        async for event in super().stream_chat(model, prompt, images, public_reasoning):
            yield event


class ExactModelCompatibilityBackend(StreamingBackend):
    def __init__(self, available_models, *, rejected_models=()):
        self.available_models = available_models
        self.rejected_models = set(rejected_models)
        self.selected = None

    async def list_models(self):
        return [{"name": name, "installed": True, "runnable": True} for name in self.available_models]

    async def stream_chat(self, model, prompt, images, public_reasoning=False):
        self.selected = model
        if model in self.rejected_models:
            raise OllamaUnavailableError(f"compatibility policy rejected exact model {model}")
        async for event in super().stream_chat(model, prompt, images, public_reasoning):
            yield event


class InferenceAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_automatic_tag_routing_fails_closed_on_invalid_compatibility_state(self):
        import json
        import tempfile
        from pathlib import Path
        from web_app.core.model_tags import ModelTag, ModelTagRegistry
        from web_app.core.native_ollama import NativeOllamaTransport
        from web_app.model_compatibility import ModelCompatibilityLayer

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": 1,
                "base_fallback_order": [],
                "models": {},
            }), encoding="utf-8")
            state = root / "state.json"
            state.write_text('{"models": ["malformed"]}', encoding="utf-8")
            compatibility = ModelCompatibilityLayer.load(policy, state)

            class NativeTransport(NativeOllamaTransport):
                async def _json_request(self, _path):
                    return {"models": [{
                        "name": "qwen3:4b",
                        "digest": "sha256:" + "a" * 64,
                    }]}

            backend = NativeTransport(
                "http://127.0.0.1:11434",
                compatibility=compatibility,
            )
            records = await backend.list_models()
            adapter = InferenceAdapter(
                backend,
                model_registry=ModelTagRegistry(
                    {"coding": ModelTag(("qwen3:4b",), ())},
                    ("qwen3:4b",),
                ),
            )

            self.assertFalse(records[0]["runnable"])
            with self.assertRaisesRegex(ValueError, "no installed model"):
                await adapter._resolve_model("coding")

    async def test_session_context_is_injected_and_reported_in_result(self):
        backend = RecordingBackend()

        def prepare_prompt(call, prompt, context):
            self.assertEqual(call.arguments["session_id"], "a" * 32)
            self.assertEqual(context.principal, "user")
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

    async def test_model_tag_resolution_excludes_quarantined_but_keeps_untested_model(self):
        from web_app.core.model_tags import ModelTag, ModelTagRegistry

        backend = CompatibilityResolvingBackend()
        registry = ModelTagRegistry(
            {"coding": ModelTag(("broken:8b", "new:8b"), ())},
            ("broken:8b", "new:8b"),
        )
        adapter = InferenceAdapter(backend, model_registry=registry)
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={"model": "coding", "prompt": "Explain"},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        events = [event async for event in adapter.execute(call, context)]

        self.assertEqual(backend.selected, "new:8b")
        self.assertEqual(events[-1].payload["effective_model_id"], "new:8b")

    async def test_missing_explicit_model_reaches_compatibility_policy_without_generic_fallback(self):
        from web_app.core.model_tags import ModelTagRegistry

        backend = ExactModelCompatibilityBackend(
            ["qwen3:4b"],
            rejected_models={"missing:8b"},
        )
        adapter = InferenceAdapter(backend, model_registry=ModelTagRegistry({}, ("qwen3:4b",)))
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={"model": "missing:8b", "prompt": "Explain"},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        with self.assertRaisesRegex(CapabilityExecutionError, "compatibility policy rejected exact model missing:8b"):
            _ = [event async for event in adapter.execute(call, context)]

        self.assertEqual(backend.selected, "missing:8b")

    async def test_explicit_rnj_model_reaches_compatibility_policy_when_only_alternate_is_installed(self):
        from web_app.core.model_tags import ModelTagRegistry

        backend = ExactModelCompatibilityBackend(["rnj-1:8b-q4"])
        adapter = InferenceAdapter(backend, model_registry=ModelTagRegistry({}, ("qwen3:4b",)))
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=".",
            arguments={"model": "rnj-1:8b", "prompt": "Explain"},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        events = [event async for event in adapter.execute(call, context)]

        self.assertEqual(backend.selected, "rnj-1:8b")
        self.assertEqual(events[-1].payload["requested_model_id"], "rnj-1:8b")


if __name__ == "__main__":
    unittest.main()
