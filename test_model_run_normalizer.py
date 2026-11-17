import importlib
import json
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from web_app import models


class CanonicalModelRunContractTests(unittest.TestCase):
    def contract(self, name):
        value = getattr(models, name, None)
        self.assertIsNotNone(value, f"missing contract {name}")
        return value

    def test_contracts_round_trip_and_reject_unknown_fields(self):
        request_type = self.contract("ModelRunCreateRequest")
        request = request_type(
            session_id="session-1",
            prompt="Review this",
            attachment_ids=["attachment-1"],
            profile="code_jury",
            public_reasoning=True,
            request_key="request-1",
        )
        self.assertEqual(request_type.model_validate_json(request.model_dump_json()), request)
        with self.assertRaises(ValidationError):
            request_type(session_id="session-1", prompt="Review", unknown=True)

    def test_juror_score_and_consensus_provenance_are_immutable(self):
        juror_type = self.contract("JurorVerdict")
        consensus_type = self.contract("ConsensusVerdict")
        with self.assertRaises(ValidationError):
            juror_type(
                model="qwen",
                score=11,
                rationale="invalid",
                original_output_id="original-1",
            )
        consensus = consensus_type(
            consensus_score=8.0,
            verdict="PASS",
            synthesis_rationale="Validated",
            synthesizer_model="qwen",
            included_jurors=("qwen",),
        )
        with self.assertRaises(ValidationError):
            consensus.included_jurors = ("other",)


class ModelRunNormalizerTests(unittest.TestCase):
    def normalizer(self):
        try:
            return importlib.import_module("web_app.model_run_normalizer")
        except ModuleNotFoundError:
            self.fail("missing web_app.model_run_normalizer")

    def test_original_digest_is_stable_and_normalization_does_not_change_content(self):
        module = self.normalizer()
        original = module.capture_original_output(
            output_id="original-1",
            model="qwen",
            content='{"summary":"Useful","content":"Final answer"}',
            reasoning_entries=[],
            provider_events=[{"type": "content", "text": "Final answer"}],
        )
        repeated = module.capture_original_output(
            output_id="different-id",
            model="qwen",
            content='{"summary":"Useful","content":"Final answer"}',
            reasoning_entries=[],
            provider_events=[{"type": "content", "text": "Final answer"}],
        )
        self.assertEqual(original.digest, repeated.digest)

        result = models.ChatResult(model="qwen", status="success", summary="Useful", content="Final answer")
        timing = models.ModelTiming(
            started_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            completed_at=datetime(2026, 11, 17, 0, 0, 1, tzinfo=timezone.utc),
            duration_ms=1000,
        )
        normalized = module.normalize_model_result(original, result, warnings=[], timing=timing)
        self.assertEqual(original.content, '{"summary":"Useful","content":"Final answer"}')
        self.assertEqual(normalized.answer, "Final answer")
        self.assertEqual(normalized.summary, "Useful")
        self.assertEqual(normalized.original_output_digest, original.digest)
        self.assertEqual(normalized.normalizer_version, 1)

    def test_unstructured_answer_uses_first_meaningful_line_without_invented_fields(self):
        module = self.normalizer()
        original = module.capture_original_output(
            output_id="original-2",
            model="small-model",
            content="\nFirst useful line\nSecond line",
            reasoning_entries=[],
            provider_events=[],
        )
        timing = models.ModelTiming(
            started_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            completed_at=None,
            duration_ms=5,
        )
        normalized = module.normalize_model_result(original, None, warnings=["unstructured"], timing=timing)
        self.assertEqual(normalized.summary, "First useful line")
        self.assertEqual(normalized.answer, "\nFirst useful line\nSecond line")
        self.assertEqual(normalized.evidence, [])
        self.assertEqual(normalized.references, [])
        self.assertEqual(normalized.warnings, ["unstructured"])
        self.assertIsNone(normalized.reasoning)

    def test_reasoning_and_typed_references_are_reused(self):
        module = self.normalizer()
        reasoning = models.ReasoningTrace(entries=[models.ReasoningEntry(
            sequence=0,
            kind="evidence",
            text="Attachment supplied the token.",
            provenance="native_provider",
        )])
        reference = models.ObjectReference(
            id="attachment-1",
            kind="attachment",
            label="evidence.txt",
            target="evidence.txt",
        )
        result = models.ChatResult(
            model="qwen",
            status="success",
            summary="Checked",
            content="Answer",
            reasoning=reasoning,
            references=[reference],
        )
        original = module.capture_original_output(
            output_id="original-3",
            model="qwen",
            content="Answer",
            reasoning_entries=reasoning.entries,
            provider_events=[],
        )
        timing = models.ModelTiming(
            started_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            completed_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            duration_ms=0,
        )
        normalized = module.normalize_model_result(original, result, warnings=[], timing=timing)
        self.assertEqual(normalized.reasoning, reasoning)
        self.assertEqual(normalized.references, [reference])
        self.assertEqual(normalized.evidence, [reference])

    def test_structured_output_fallback_is_disclosed_as_a_warning(self):
        module = self.normalizer()
        result = models.ChatResult(
            model="qwen3.5:9b",
            status="success",
            summary="Plain response",
            content="Plain response",
            error="structured_output_fallback",
        )
        original = module.capture_original_output(
            output_id="original-4",
            model="qwen3.5:9b",
            content="Plain response",
            reasoning_entries=[],
            provider_events=[],
        )
        timing = models.ModelTiming(
            started_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            completed_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            duration_ms=0,
        )

        normalized = module.normalize_model_result(original, result, warnings=[], timing=timing)

        self.assertEqual(normalized.status, "completed")
        self.assertEqual(normalized.warnings, ["Model returned plain text; JSON_CODR normalized the response."])


if __name__ == "__main__":
    unittest.main()
