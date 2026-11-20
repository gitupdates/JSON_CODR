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
        return f"ACTIVE SKILL:\n{suffix}\n\nUSER REQUEST:\n{prompt}", ([Path("image.png")] if supports_vision else []), {
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
        self.outlier_once = set()
        self.missing_labels_once = set()
        self.inline_labels_once = set()
        self.installed_models = ["model-b", "model-a"]

    async def list_models(self):
        return ([{"name": model, "installed": True} for model in self.installed_models]
                + [{"name": "missing", "installed": False}])

    async def supports_vision(self, model):
        return model == "model-b"

    async def chat(self, model, prompt, images=None, allow_repair=True):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        self.calls.append((model, prompt, list(images or [])))
        await asyncio.sleep(0)
        self.active -= 1
        if model in self.fail:
            raise RuntimeError("provider failed")
        content = f"answer {model}"
        if model in self.outlier_once:
            self.outlier_once.remove(model)
            content = ""
        if model in self.missing_labels_once:
            self.missing_labels_once.remove(model)
            content = "A useful answer without the requested labels."
        if model in self.inline_labels_once:
            self.inline_labels_once.remove(model)
            content = "PURPOSE: Adds values; RISKS: No validation; IMPROVEMENT: Validate inputs."
        if "RESPONSE FORMAT CORRECTION" in prompt:
            content = "PURPOSE: Adds two values.\nRISKS: Inputs are not validated.\nIMPROVEMENT: Validate numeric inputs."
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
            concurrency=4,
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

    async def test_single_model_record_uses_the_same_format_consistency_contract(self):
        run = self.service.record_single(
            session_id="a" * 32,
            prompt="Return exactly this format:\nVOTE: <GO or NO GO>\nRISKS: <primary risk>",
            requested_model="model-a",
            result=ChatResult(
                model="model-a",
                status="success",
                summary="GO",
                content="VOTE: GO",
                provider_events=[{"type": "provider.audit", "value": "kept"}],
            ),
        )

        result = run.results[0]
        original = self.service.store.get_original(run.run_id, result.result_id)
        self.assertFalse(result.consistency.format_compliant)
        self.assertEqual(result.consistency.missing_labels, ["RISKS"])
        self.assertEqual(original.provider_events, [{"type": "provider.audit", "value": "kept"}])

    async def test_requested_parallelism_is_persisted_and_limits_only_that_run(self):
        self.inference.installed_models = ["model-a", "model-b", "model-c", "model-d"]
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt="Review concurrently",
            parallelism=3,
        ))

        await self.service.run(run.run_id)

        finished = self.service.get(run.run_id)
        self.assertEqual(finished.parallelism, 3)
        self.assertEqual(self.inference.maximum, 3)

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

    async def test_each_model_receives_the_same_delimited_contract_with_its_exact_identifier(self):
        run = await self.create()

        await self.service.run(run.run_id)

        calls = {model: prompt for model, prompt, _ in self.inference.calls}
        for model, prompt in calls.items():
            self.assertIn("CANONICAL MULTI-MODEL REQUEST", prompt)
            self.assertIn(f"REQUESTED MODEL IDENTIFIER: {model}", prompt)
            self.assertIn("USER TASK (authoritative):\nReview once", prompt)
            self.assertIn("ACTIVE SKILLS AND REFERENCE CONTEXT:", prompt)
            self.assertIn("ACTIVE SKILL:\n", prompt)
            self.assertEqual(prompt.count("USER TASK (authoritative):\nReview once"), 1)
            self.assertNotIn("USER REQUEST:\nReview once", prompt)
            self.assertIn("JSON_CODR normalizes comparable fields", prompt)
            self.assertIn(
                "JSON_CODR, not this model, coordinates any multi-model run",
                prompt,
            )
            self.assertNotIn("use the requested model identifier", prompt)

    async def test_outlier_gets_one_targeted_format_repair_and_both_outputs_are_auditable(self):
        self.inference.outlier_once.add("model-a")
        run = await self.create()

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 2)
        self.assertIn("EMPTY RESPONSE CORRECTION", calls[1][1])
        result = next(item for item in self.service.get(run.run_id).results if item.requested_model == "model-a")
        self.assertEqual(result.status, "completed")
        original = self.service.store.get_original(run.run_id, result.result_id)
        self.assertEqual(original.content, "answer model-a")
        self.assertEqual(original.provider_events[0]["initial_content"], "")

    async def test_missing_explicit_labels_gets_one_auditable_alignment_retry(self):
        self.inference.missing_labels_once.add("model-a")
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt=(
                "Review the function. Return exactly these labeled sections: "
                "PURPOSE: <one sentence>; RISKS: <one sentence>; IMPROVEMENT: <one sentence>."
            ),
        ))

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 2)
        self.assertIn("RESPONSE FORMAT CORRECTION", calls[1][1])
        self.assertIn("MISSING LABELS: PURPOSE, RISKS, IMPROVEMENT", calls[1][1])
        result = next(item for item in self.service.get(run.run_id).results if item.requested_model == "model-a")
        self.assertEqual(result.status, "completed")
        self.assertIn("PURPOSE:", result.answer)
        self.assertTrue(result.consistency.format_compliant)
        self.assertEqual(result.consistency.required_labels, ["PURPOSE", "RISKS", "IMPROVEMENT"])
        self.assertTrue(result.consistency.answer_matches_original)
        original = self.service.store.get_original(run.run_id, result.result_id)
        alignment = next(event for event in original.provider_events if event["type"] == "format_alignment")
        self.assertEqual(alignment["initial_content"], "A useful answer without the requested labels.")
        self.assertIn("PURPOSE:", alignment["repaired_content"])

    async def test_inline_explicit_labels_are_compliant_without_retry(self):
        self.inference.inline_labels_once.add("model-a")
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt=(
                "Return exactly these labeled sections: PURPOSE: <text>; RISKS: <text>; "
                "IMPROVEMENT: <text>."
            ),
        ))

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 1)

    async def test_uppercase_colon_in_ordinary_content_is_not_a_format_contract(self):
        self.inference.missing_labels_once.add("model-a")
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt="Review this log: ERROR: connection failed.",
        ))

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 1)

    async def test_source_after_explicit_contract_does_not_add_labels(self):
        self.inference.inline_labels_once.add("model-a")
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt=(
                "Return exactly these labeled sections: PURPOSE: <text>; RISKS: <text>; "
                "IMPROVEMENT: <text>. Now review this log:\nERROR: connection failed."
            ),
        ))

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 1)

    async def test_multiline_explicit_contract_is_detected_without_absorbing_log_labels(self):
        self.inference.missing_labels_once.add("model-a")
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt=(
                "Return exactly this format:\nPURPOSE: <one sentence>\nRISKS: <one sentence>\n"
                "IMPROVEMENT: <one sentence>\nConsider this log:\nERROR: connection failed."
            ),
        ))

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 2)
        self.assertIn("MISSING LABELS: PURPOSE, RISKS, IMPROVEMENT", calls[1][1])
        self.assertNotIn("MISSING LABELS: PURPOSE, RISKS, IMPROVEMENT, ERROR", calls[1][1])

    async def test_schema_repair_consumes_the_single_repair_budget(self):
        original_chat = self.inference.chat

        async def schema_repaired(model, prompt, images=None, allow_repair=True):
            result = await original_chat(model, prompt, images=images, allow_repair=allow_repair)
            if model == "model-a":
                return result.model_copy(update={
                    "content": "",
                    "provider_events": [{"type": "schema_repair", "initial_raw": "broken", "repaired_raw": "fixed"}],
                })
            return result

        self.inference.chat = schema_repaired
        run = await self.create()

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 1)
        result = next(item for item in self.service.get(run.run_id).results if item.requested_model == "model-a")
        self.assertIn("after one repair attempt", result.warnings[0])

    async def test_consumed_repair_budget_still_discloses_missing_required_labels(self):
        original_chat = self.inference.chat

        async def schema_repaired(model, prompt, images=None, allow_repair=True):
            result = await original_chat(model, prompt, images=images, allow_repair=allow_repair)
            if model == "model-a":
                return result.model_copy(update={
                    "content": "Useful but unlabeled answer.",
                    "provider_events": [{"type": "schema_repair", "initial_raw": "broken", "repaired_raw": "fixed"}],
                })
            return result

        self.inference.chat = schema_repaired
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt="Return exactly these labeled sections: PURPOSE: <text>; RISKS: <text>.",
        ))

        await self.service.run(run.run_id)

        calls = [call for call in self.inference.calls if call[0] == "model-a"]
        self.assertEqual(len(calls), 1)
        result = next(item for item in self.service.get(run.run_id).results if item.requested_model == "model-a")
        self.assertIn("Model omitted required response labels", result.warnings[0])

    async def test_failed_format_repair_preserves_the_initial_provider_response(self):
        self.inference.outlier_once.add("model-a")
        original_chat = self.inference.chat

        async def fail_repair(model, prompt, images=None, allow_repair=True):
            if model == "model-a" and "EMPTY RESPONSE CORRECTION" in prompt:
                raise RuntimeError("repair unavailable")
            return await original_chat(model, prompt, images=images, allow_repair=allow_repair)

        self.inference.chat = fail_repair
        run = await self.create()

        await self.service.run(run.run_id)

        result = next(item for item in self.service.get(run.run_id).results if item.requested_model == "model-a")
        original = self.service.store.get_original(run.run_id, result.result_id)
        self.assertEqual(original.content, "")
        self.assertEqual(original.provider_events[-1]["error"], "RuntimeError: repair unavailable")
        self.assertIn("initial provider response was preserved", result.warnings[0])

    async def test_code_jury_prompt_does_not_request_the_general_response_prefix(self):
        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt="Review the change",
            profile="code_jury",
        ))

        await self.service.run(run.run_id)

        for _, prompt, _ in self.inference.calls:
            self.assertIn("Return only JSON", prompt)
            self.assertNotIn("Put the direct answer in content beginning exactly", prompt)

    async def test_empty_installed_roster_is_terminal(self):
        self.inference.installed_models = []

        run = await self.service.create(ModelRunCreateRequest(
            session_id="a" * 32,
            prompt="Review once",
        ))
        await self.service.run(run.run_id)

        self.assertEqual(self.service.get(run.run_id).status, "failed")

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
