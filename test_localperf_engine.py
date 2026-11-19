import json
import tempfile
import unittest
from pathlib import Path


class LocalPerfEngineTests(unittest.TestCase):
    def sample(self, prompt_id="lp-01", repetition=1, rate=20.0):
        from web_app.localperf.models import SampleRecord
        return SampleRecord(prompt_id=prompt_id, repetition=repetition, success=True,
            generation_tokens_per_second=rate, ttft_ms=10, peak_vram_mb=0,
            total_duration_ms=100, prompt_tokens=5, generated_tokens=2, output="ok")

    def metadata(self):
        return {"model":"qwen", "backend":"cpu", "profile":"automatic", "hardware":{"cpu":"x"}, "software":{"app":"V1.0.10"}}

    def test_aggregate_is_conforming_only_with_complete_workload_and_quality(self):
        from web_app.localperf.aggregate import aggregate_run
        from web_app.localperf.quality import evaluate_quality
        samples = []
        outputs = {"lp-07":"def clamp(value, minimum, maximum): return max(minimum,min(value,maximum))",
                   "lp-08":"def deduplicate(items): return list(dict.fromkeys(items))",
                   "lp-09":'{"status":"ok","items":[1,2]}', "lp-10":"SELECT name FROM users WHERE id = ?"}
        for index in range(1, 13):
            sample = self.sample(f"lp-{index:02d}")
            if sample.prompt_id in outputs:
                sample.output = outputs[sample.prompt_id]
                sample.quality = evaluate_quality(sample.prompt_id, sample.output)
            samples.append(sample)
        run = aggregate_run(samples, self.metadata(), "quick", 1)
        self.assertTrue(run.conformance.conforming)
        self.assertEqual(run.metrics["generation_tokens_per_second"].median, 20)

    def test_missing_prompt_is_ineligible(self):
        from web_app.localperf.aggregate import aggregate_run
        run = aggregate_run([self.sample()], self.metadata(), "quick", 1)
        self.assertFalse(run.conformance.eligible)
        self.assertIn("incomplete_samples", run.conformance.reasons)

    def test_atomic_storage_writes_aggregate_and_jsonl_then_can_clear_legacy(self):
        from web_app.localperf.aggregate import aggregate_run
        from web_app.localperf.storage import LocalPerfStorage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = LocalPerfStorage(root)
            run = aggregate_run([self.sample()], self.metadata(), "quick", 1)
            paths = storage.save_run(run)
            self.assertTrue(paths["aggregate"].is_file())
            self.assertTrue(paths["samples"].is_file())
            self.assertEqual(json.loads(paths["aggregate"].read_text())["schema_version"], "0.3.0-localperf")
            legacy = root / "hardware-benchmarks.json"
            legacy.write_text("[]")
            self.assertTrue(storage.clear_legacy_history())
            self.assertFalse(legacy.exists())

    def test_paired_comparison_refuses_mismatched_samples(self):
        from web_app.localperf.statistics import compare_sample_sets
        with self.assertRaises(ValueError):
            compare_sample_sets([self.sample("lp-01")], [self.sample("lp-02")])

    def test_paired_comparison_reports_probability_and_interval(self):
        from web_app.localperf.statistics import compare_sample_sets
        baseline = [self.sample(f"lp-{i:02d}", rate=10) for i in range(1, 4)]
        candidate = [self.sample(f"lp-{i:02d}", rate=20) for i in range(1, 4)]
        report = compare_sample_sets(baseline, candidate, resamples=500, seed=7)
        self.assertEqual(report["relative_change"], 1.0)
        self.assertGreater(report["probability_superior"], .99)
        self.assertEqual(len(report["confidence_interval"]), 2)


if __name__ == "__main__":
    unittest.main()
