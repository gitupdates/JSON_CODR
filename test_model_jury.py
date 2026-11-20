import json
import unittest
from datetime import datetime, timezone

from web_app.models import CanonicalModelResult, ModelTiming


class ModelJuryTests(unittest.TestCase):
    def result(self, model, payload):
        return CanonicalModelResult(
            result_id=f"result-{model}",
            requested_model=model,
            effective_model=model,
            status="completed",
            timing=ModelTiming(started_at=datetime.now(timezone.utc), duration_ms=1),
            original_output_id=f"original-{model}",
            original_output_digest="sha256:" + "1" * 64,
            answer=payload,
        )

    def test_validates_strict_juror_json_and_preserves_invalid_original_reference(self):
        from web_app.model_jury import JuryValidationError, validate_juror_result

        valid = validate_juror_result(self.result("a", json.dumps({
            "score": 9, "critical_issues": [], "rationale": "Strong with evidence",
        })))
        self.assertEqual((valid.model, valid.score, valid.original_output_id), ("a", 9, "original-a"))
        with self.assertRaises(JuryValidationError) as caught:
            validate_juror_result(self.result("b", '{"score": 12}'))
        self.assertEqual(caught.exception.original_output_id, "original-b")

    def test_consensus_uses_server_arithmetic_thresholds_and_complete_provenance(self):
        from web_app.model_jury import build_consensus, validate_juror_result

        verdicts = [
            validate_juror_result(self.result("a", '{"score":9,"critical_issues":[],"rationale":"a"}')),
            validate_juror_result(self.result("b", '{"score":7,"critical_issues":[],"rationale":"b"}')),
        ]
        consensus = build_consensus(
            verdicts,
            ["model-c"],
            [("synth", lambda _: {"agreed_issues": ["one"], "dissenting_notes": ["two"], "synthesis_rationale": "combined"})],
        )
        self.assertEqual(consensus.consensus_score, 8.0)
        self.assertEqual(consensus.verdict, "PASS")
        self.assertEqual(consensus.included_jurors, ("a", "b"))
        self.assertEqual(consensus.excluded_jurors, ("model-c",))
        self.assertEqual(consensus.synthesizer_model, "synth")

    def test_critical_issue_overrides_score_and_synthesizer_falls_back(self):
        from web_app.model_jury import build_consensus, validate_juror_result

        verdict = validate_juror_result(self.result(
            "a", '{"score":10,"critical_issues":["remote execution"],"rationale":"unsafe"}',
        ))
        def broken(_):
            raise RuntimeError("offline")
        consensus = build_consensus(
            [verdict], [], [("broken", broken), ("fallback", lambda _: {"synthesis_rationale": "fallback worked"})],
        )
        self.assertEqual(consensus.verdict, "FAIL")
        self.assertEqual(consensus.synthesizer_model, "fallback")

    def test_total_synthesis_failure_retains_deterministic_consensus(self):
        from web_app.model_jury import build_consensus, validate_juror_result

        verdict = validate_juror_result(self.result(
            "a", '{"score":6,"critical_issues":[],"rationale":"mixed"}',
        ))
        def broken(_):
            raise RuntimeError("offline")
        consensus = build_consensus([verdict], [], [("broken", broken)])
        self.assertEqual((consensus.consensus_score, consensus.verdict), (6.0, "CONDITIONAL_PASS"))
        self.assertEqual(consensus.synthesizer_model, "unavailable")
        self.assertIn("failed", consensus.synthesis_rationale)


if __name__ == "__main__":
    unittest.main()
