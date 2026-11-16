from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class BaselineArtifact:
    path: Path
    model_count: int
    integrity_count: int
    performance_session_count: int


class BenchmarkBaselineService:
    def __init__(self, data_root: Path) -> None:
        self.root = Path(data_root).resolve() / "benchmark-baselines"

    def export(self, integrity_history: list[dict], performance_history: list[dict]) -> BaselineArtifact:
        integrity = copy.deepcopy(integrity_history)
        performance = copy.deepcopy(performance_history)
        latest = self._latest_strict_results(integrity)
        best_performance = self._best_performance(performance)
        rows = []
        for model, result in latest.items():
            scores = result.get("scores", {})
            evidence = best_performance.get(model)
            rows.append({
                "model": model,
                "integrity": scores.get("integrity"),
                "comprehension": scores.get("comprehension"),
                "overall": scores.get("overall"),
                "performance_index": evidence["performance_index"] if evidence else None,
                "performance_session_id": evidence["session_id"] if evidence else None,
                "performance_backend": evidence["backend"] if evidence else None,
                "integrity_evaluation_id": result.get("id"),
            })
        rows.sort(key=lambda row: (
            -(self._number(row["overall"]) or 0),
            row["performance_index"] is None,
            -(self._number(row["performance_index"]) or 0),
            row["model"].lower(),
        ))
        tier = 0
        previous_score = object()
        for rank, row in enumerate(rows, 1):
            if row["overall"] != previous_score:
                tier += 1
                previous_score = row["overall"]
            row["rank"] = rank
            row["capability_tier"] = tier

        created_at = datetime.now(timezone.utc)
        payload = {
            "schema_version": "1.0",
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "ranking_policy": {
                "name": "capability-first",
                "ordering": [
                    "integrity_comprehension_overall_desc",
                    "verified_performance_present_desc",
                    "performance_index_desc",
                ],
            },
            "summary": {
                "ranked_models": len(rows),
                "integrity_evaluations": len(integrity),
                "performance_sessions": len(performance),
            },
            "holistic_ranking": rows,
            "integrity_history": integrity,
            "performance_history": performance,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        filename = f"JSON_CODR-benchmark-baseline-{created_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        path = self.root / filename
        temporary = self.root / f".{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        return BaselineArtifact(path, len(rows), len(integrity), len(performance))

    @staticmethod
    def _number(value: object) -> float | None:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @classmethod
    def _latest_strict_results(cls, history: list[dict]) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for item in sorted(history, key=lambda value: str(value.get("created_at", "")), reverse=True):
            model = str(item.get("model", "")).strip()
            if model and item.get("suite_version") == "Integrity-Comprehension-v2" and model not in results:
                results[model] = item
        return results

    @classmethod
    def _best_performance(cls, history: list[dict]) -> dict[str, dict]:
        best: dict[str, dict] = {}
        for session in history:
            model = str(session.get("model", "")).strip()
            if not model:
                continue
            for result in session.get("results", []):
                speedup = cls._number(result.get("speedup_vs_cpu"))
                conforming = result.get("localperf", {}).get("conformance", {}).get("conforming") is True
                if result.get("status") != "completed" or not conforming or speedup is None:
                    continue
                candidate = {
                    "performance_index": round(speedup * 100, 3),
                    "session_id": session.get("id"),
                    "backend": result.get("backend"),
                }
                if model not in best or candidate["performance_index"] > best[model]["performance_index"]:
                    best[model] = candidate
        return best
