import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
MODULE = ROOT / "web" / "benchmark_leaderboard.js"


def run_helper(expression, payload):
    script = f"""
require({json.dumps(str(MODULE))});
const input = {json.dumps(payload)};
const output = {expression};
process.stdout.write(JSON.stringify(output));
"""
    completed = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return json.loads(completed.stdout)


def session(session_id="run-1", created_at="2026-11-15T12:00:00Z"):
    return {
        "id": session_id,
        "created_at": created_at,
        "suite": "quick",
        "model": "qwen:7b",
        "workload_version": "LocalPerf-Core-v1",
        "workload_hash": "abc123",
        "results": [
            {
                "backend": "cpu",
                "name": "CPU",
                "status": "completed",
                "verified": True,
                "tokens_per_second": 20,
                "average_total_seconds": 2,
                "speedup_vs_cpu": 1,
                "tests": [
                    {"tokens_per_second": 18, "ttft_ms": 600, "total_seconds": 2.1, "peak_vram_mb": 0},
                    {"tokens_per_second": 22, "ttft_ms": 500, "total_seconds": 1.9, "peak_vram_mb": 0},
                ],
                "localperf": {"evaluation_id": "cpu-eval", "conformance": {"conforming": True}},
            },
            {
                "backend": "cuda_v12",
                "name": "CUDA 12",
                "status": "completed",
                "verified": False,
                "tokens_per_second": 30,
                "average_total_seconds": 1.2,
                "speedup_vs_cpu": 1.5,
                "tests": [
                    {"tokens_per_second": 28, "ttft_ms": 300, "total_seconds": 1.3, "peak_vram_mb": 6000},
                    {"tokens_per_second": 32, "ttft_ms": 260, "total_seconds": 1.1, "peak_vram_mb": 6100},
                ],
                "localperf": {"evaluation_id": "cuda-eval", "conformance": {"conforming": True}},
            },
            {
                "backend": "vulkan",
                "name": "Vulkan",
                "status": "completed",
                "tokens_per_second": 35,
                "speedup_vs_cpu": 1.75,
                "tests": [],
                "localperf": {"conformance": {"conforming": False}},
            },
        ],
    }


class BenchmarkLeaderboardTests(unittest.TestCase):
    def test_build_rows_keeps_concrete_backends_and_adds_detected_untested_options(self):
        payload = {
            "history": [session()],
            "candidates": [
                {"id": "cpu", "name": "CPU"},
                {"id": "cuda_v12", "name": "CUDA 12"},
                {"id": "cuda_v13", "name": "CUDA 13"},
                {"id": "npu-0", "name": "Intel NPU"},
            ],
        }
        rows = run_helper(
            "globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1')",
            payload,
        )
        self.assertEqual([row["backend"] for row in rows], ["cpu", "cuda_v12", "vulkan", "cuda_v13", "npu-0"])
        self.assertEqual(rows[1]["performance_index"], 150)
        self.assertFalse(rows[1]["probe_verified"])
        self.assertEqual(rows[3]["status"], "not_tested")
        self.assertIsNone(rows[3]["performance_index"])

    def test_filter_and_rank_excludes_invalid_rows_from_verified_rank(self):
        payload = {"history": [session()], "candidates": []}
        ranked = run_helper(
            "globalThis.JSONCodrLeaderboard.filterAndRank(globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1'), {metric:'tokens_per_second'})",
            payload,
        )
        self.assertEqual([row["backend"] for row in ranked], ["cuda_v12", "cpu", "vulkan"])
        self.assertEqual([row["rank"] for row in ranked], [1, 2, None])

        missing_metric = run_helper(
            "globalThis.JSONCodrLeaderboard.filterAndRank(input.rows, {metric:'ttft_ms'})",
            {"rows": [{"id": "legacy", "eligible_rank": True, "ttft_ms": None}]},
        )
        self.assertIsNone(missing_metric[0]["rank"])

    def test_percentiles_and_legacy_missing_fields_are_stable(self):
        stats = run_helper(
            "({stats:globalThis.JSONCodrLeaderboard.percentiles(input.values), rows:globalThis.JSONCodrLeaderboard.buildRows(input.history, [], 'legacy')})",
            {"values": [1, 2, 3, 4, 5], "history": [{"id": "legacy", "results": [{"backend": "cpu"}]}]},
        )
        self.assertEqual(stats["stats"], {"min": 1, "p50": 3, "p90": 4.6, "max": 5})
        self.assertEqual(stats["rows"][0]["status"], "unavailable")
        self.assertIsNone(stats["rows"][0]["ttft_ms"])

        null_metrics = run_helper(
            "globalThis.JSONCodrLeaderboard.buildRows(input.history, [], 'nulls')[0]",
            {"history": [{"id": "nulls", "results": [{"backend": "gpu", "tokens_per_second": None, "speedup_vs_cpu": None}]}]},
        )
        self.assertIsNone(null_metrics["tokens_per_second"])
        self.assertIsNone(null_metrics["speedup_vs_cpu"])
        self.assertIsNone(null_metrics["performance_index"])

    def test_trend_requires_matching_model_suite_workload_and_backend(self):
        first = session("run-1", "2026-11-15T12:00:00Z")
        second = session("run-2", "2026-11-16T12:00:00Z")
        second["results"][1]["tokens_per_second"] = 33
        wrong_model = session("run-3", "2026-11-17T12:00:00Z")
        wrong_model["model"] = "other:7b"
        payload = {"history": [wrong_model, second, first], "candidates": []}
        trend = run_helper(
            "(()=>{const rows=globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1'); return globalThis.JSONCodrLeaderboard.buildTrend(input.history, rows.find(row=>row.backend==='cuda_v12'));})()",
            payload,
        )
        self.assertEqual([point["session_id"] for point in trend], ["run-1", "run-2"])
        self.assertEqual([point["value"] for point in trend], [30, 33])

        ttft_trend = run_helper(
            "(()=>{const rows=globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1'); return globalThis.JSONCodrLeaderboard.buildTrend(input.history, rows.find(row=>row.backend==='cuda_v12'), 'ttft_ms');})()",
            payload,
        )
        self.assertEqual([point["value"] for point in ttft_trend], [280, 280])

        second["results"][1]["localperf"]["conformance"]["conforming"] = False
        gap_trend = run_helper(
            "(()=>{const rows=globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1'); return globalThis.JSONCodrLeaderboard.buildTrend(input.history, rows.find(row=>row.backend==='cuda_v12'));})()",
            payload,
        )
        self.assertEqual(gap_trend[0]["value"], 30)
        self.assertTrue(gap_trend[0]["eligible"])
        self.assertIsNone(gap_trend[1]["value"])
        self.assertFalse(gap_trend[1]["eligible"])

        missing_backend = session("run-4", "2026-11-18T12:00:00Z")
        missing_backend["results"] = [missing_backend["results"][0]]
        payload["history"].append(missing_backend)
        missing_trend = run_helper(
            "(()=>{const rows=globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1'); return globalThis.JSONCodrLeaderboard.buildTrend(input.history, rows.find(row=>row.backend==='cuda_v12'));})()",
            payload,
        )
        self.assertIsNone(missing_trend[-1]["value"])
        self.assertFalse(missing_trend[-1]["eligible"])

    def test_candidate_readiness_and_session_selection_are_preserved(self):
        candidate = run_helper(
            "globalThis.JSONCodrLeaderboard.buildRows(input.history, input.candidates, 'run-1').at(-1)",
            {
                "history": [session()],
                "candidates": [{"id": "npu-0", "name": "Intel NPU", "runnable": False, "compatible": False, "reason": "Runtime missing"}],
            },
        )
        self.assertFalse(candidate["runnable"])
        self.assertFalse(candidate["compatible"])
        self.assertEqual(candidate["availability_reason"], "Runtime missing")
        self.assertEqual(candidate["status"], "unavailable")
        self.assertFalse(candidate["tested"])

        selected = run_helper(
            "globalThis.JSONCodrLeaderboard.chooseSession(input.history, 'run-2', 'all', 'all').id",
            {"history": [session("run-1"), session("run-2")]},
        )
        self.assertEqual(selected, "run-2")

    def test_scale_points_handles_empty_single_and_constant_domains(self):
        scaled = run_helper(
            "({empty:globalThis.JSONCodrLeaderboard.scalePoints([], input.bounds), single:globalThis.JSONCodrLeaderboard.scalePoints([{x:4,y:9}], input.bounds), constant:globalThis.JSONCodrLeaderboard.scalePoints([{x:2,y:3},{x:2,y:3}], input.bounds)})",
            {"bounds": {"width": 400, "height": 200, "padding": 20}},
        )
        self.assertEqual(scaled["empty"], [])
        for group in (scaled["single"], scaled["constant"]):
            for point in group:
                self.assertIsInstance(point["cx"], (int, float))
                self.assertIsInstance(point["cy"], (int, float))
                self.assertGreaterEqual(point["cx"], 20)
                self.assertLessEqual(point["cx"], 380)

    def test_select_row_keeps_visible_selection_or_falls_back_deterministically(self):
        selected = run_helper(
            "({kept:globalThis.JSONCodrLeaderboard.selectRow(input.rows, 'b').id, fallback:globalThis.JSONCodrLeaderboard.selectRow(input.rows, 'missing').id, empty:globalThis.JSONCodrLeaderboard.selectRow([], 'b')})",
            {"rows": [{"id": "a"}, {"id": "b"}]},
        )
        self.assertEqual(selected, {"kept": "b", "fallback": "a", "empty": None})


if __name__ == "__main__":
    unittest.main()
