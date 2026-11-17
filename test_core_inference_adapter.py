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


if __name__ == "__main__":
    unittest.main()
