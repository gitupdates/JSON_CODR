import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web_app.model_run_store import ModelRunStore
from web_app.models import ChatResult, ModelRunCreateRequest, SessionRecord


class FakeWorkspace:
    def __init__(self):
        self.session = SessionRecord(
            id="a" * 32,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def get_session(self, session_id):
        if session_id != self.session.id:
            raise KeyError(session_id)
        return self.session


class FakeContext:
    def __init__(self):
        self.calls = []

    def build_for_model(self, session, prompt, supports_vision):
        self.calls.append((prompt, supports_vision))
        suffix = "image-original" if supports_vision else "ocr-text"
        return f"{prompt}\n{suffix}", ([Path("image.png")] if supports_vision else []), {
            "image_sources": ["image.png"] if supports_vision else [],
            "text_sources": [] if supports_vision else ["image.png:ocr"],
            "omitted_modalities": [],
            "adaptations": [suffix],
        }


class FakeInference:
    def __init__(self):
        self.active = 0
        self.maximum = 0
        self.calls = []
        self.fail = set()

    async def list_models(self):
        return [
            {"name": "model-b", "installed": True},
            {"name": "missing", "installed": False},
            {"name": "model-a", "installed": True},
        ]

    async def supports_vision(self, model):
        return model == "model-b"

    async def chat(self, model, prompt, images=None):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        self.calls.append((model, prompt, list(images or [])))
        await asyncio.sleep(0)
        self.active -= 1
        if model in self.fail:
            raise RuntimeError("provider failed")
        content = f"answer {model}"
        if prompt.startswith("CODE JURY CRITERIA:"):
            content = '{"score": 8, "critical_issues": [], "rationale": "Verified by the juror."}'
        return ChatResult(model=model, status="success", summary=f"summary {model}", content=content)


class ModelRunServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.inference = FakeInference()
        self.context = FakeContext()
        from web_app.model_runs import ModelRunService

        self.service = ModelRunService(
            ModelRunStore(Path(self.temp.name)),
            self.inference,
            FakeWorkspace(),
            self.context,
            concurrency=2,
        )

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def create(self, profile="general"):
        return await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt="Review once",
            profile=profile,
            request_key=f"request-{profile}",
        ))

    async def test_snapshots_installed_roster_reports_unavailable_and_preserves_order(self):
        run = await self.create()
        self.assertEqual(run.roster, ["model-b", "model-a"])
        self.assertEqual(run.unavailable_models, ["missing"])
        await self.service.run(run.run_id)
        completed = self.service.get(run.run_id)
        self.assertEqual([item.requested_model for item in completed.results], ["model-b", "model-a"])
        self.assertEqual([call[0] for call in self.inference.calls], ["model-b", "model-a"])
        self.assertLessEqual(self.inference.maximum, 2)

    async def test_multimodal_input_is_adapted_per_model_and_prompt_is_shared(self):
        run = await self.create()
        await self.service.run(run.run_id)
        calls = {model: (prompt, images) for model, prompt, images in self.inference.calls}
        self.assertIn("image-original", calls["model-b"][0])
        self.assertEqual(calls["model-b"][1], [Path("image.png")])
        self.assertIn("ocr-text", calls["model-a"][0])
        self.assertEqual(calls["model-a"][1], [])
        results = {item.requested_model: item for item in self.service.get(run.run_id).results}
        self.assertEqual(results["model-b"].input_manifest.image_sources, ["image.png"])
        self.assertEqual(results["model-a"].input_manifest.text_sources, ["image.png:ocr"])

    async def test_partial_failure_is_persisted_without_losing_other_results(self):
        self.inference.fail.add("model-b")
        run = await self.create()
        await self.service.run(run.run_id)
        finished = self.service.get(run.run_id)
        self.assertEqual(finished.status, "partial")
        self.assertEqual({item.requested_model: item.status for item in finished.results}, {
            "model-b": "failed", "model-a": "completed",
        })

    async def test_code_jury_uses_identical_server_owned_criteria(self):
        run = await self.create("code_jury")
        await self.service.run(run.run_id)
        prompts = [prompt for _, prompt, _ in self.inference.calls]
        criteria = [prompt.split("CODE JURY CRITERIA:\n", 1)[1].split("\n\n", 1)[0] for prompt in prompts]
        self.assertEqual(len(set(criteria)), 1)

    async def test_code_jury_persists_validated_consensus_after_jurors_finish(self):
        run = await self.create("code_jury")

        await self.service.run(run.run_id)

        finished = self.service.get(run.run_id)
        self.assertEqual(finished.consensus.verdict, "PASS")
        self.assertEqual(finished.consensus.consensus_score, 8)
        self.assertEqual(finished.consensus.included_jurors, ("model-b", "model-a"))
        self.assertEqual(finished.consensus.synthesizer_model, "unavailable")

    async def test_recovery_marks_abandoned_work_failed(self):
        run = await self.create()
        await self.service.recover_incomplete_runs()
        recovered = self.service.get(run.run_id)
        self.assertEqual(recovered.status, "failed")
        self.assertTrue(all(item.error_code == "server_restart" for item in recovered.results))


if __name__ == "__main__":
    unittest.main()
