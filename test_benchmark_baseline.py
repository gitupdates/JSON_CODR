import json
import tempfile
import unittest
from pathlib import Path

from web_app.benchmark_baseline import BenchmarkBaselineService


class BenchmarkBaselineTests(unittest.TestCase):
    def test_export_preserves_histories_and_ranks_capability_before_performance(self):
        integrity = [
            {"id": "high", "suite_version": "Integrity-Comprehension-v2", "created_at": "2026-11-15T12:00:00Z",
             "model": "high:7b", "scores": {"integrity": 90, "comprehension": 90, "overall": 90}, "scenarios": []},
            {"id": "middle", "suite_version": "Integrity-Comprehension-v2", "created_at": "2026-11-15T12:00:00Z",
             "model": "middle:7b", "scores": {"integrity": 75, "comprehension": 75, "overall": 75}, "scenarios": []},
            {"id": "legacy", "suite_version": "Integrity-Comprehension-v1", "created_at": "2026-11-15T13:00:00Z",
             "model": "legacy:7b", "scores": {"integrity": 100, "comprehension": 100, "overall": 100}, "scenarios": []},
        ]
        performance = [{"id": "perf", "model": "middle:7b", "results": [{
            "backend": "gpu", "status": "completed", "speedup_vs_cpu": 10,
            "localperf": {"conformance": {"conforming": True}},
        }]}]
        original_integrity = json.loads(json.dumps(integrity))
        original_performance = json.loads(json.dumps(performance))

        with tempfile.TemporaryDirectory() as directory:
            artifact = BenchmarkBaselineService(Path(directory)).export(integrity, performance)
            payload = json.loads(artifact.path.read_text(encoding="utf-8"))

        self.assertEqual(integrity, original_integrity)
        self.assertEqual(performance, original_performance)
        self.assertEqual(payload["integrity_history"], integrity)
        self.assertEqual(payload["performance_history"], performance)
        self.assertEqual(payload["ranking_policy"]["ordering"], [
            "integrity_comprehension_overall_desc", "verified_performance_present_desc", "performance_index_desc"
        ])
        self.assertEqual([row["model"] for row in payload["holistic_ranking"]], ["high:7b", "middle:7b"])
        self.assertEqual([row["capability_tier"] for row in payload["holistic_ranking"]], [1, 2])
        self.assertEqual(payload["holistic_ranking"][1]["performance_index"], 1000)
        self.assertRegex(artifact.path.name, r"^JSON_CODR-benchmark-baseline-\d{8}T\d{6}Z\.json$")


if __name__ == "__main__":
    unittest.main()
