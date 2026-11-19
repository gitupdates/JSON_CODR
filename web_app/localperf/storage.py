from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from web_app.localperf.models import LocalPerfRun


class LocalPerfStorage:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).resolve()
        self.runs_root = self.data_root / "localperf" / "runs"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)

    def save_run(self, run: LocalPerfRun) -> dict[str, Path]:
        directory = self.runs_root / run.evaluation_id
        aggregate = directory / "aggregate.json"
        samples = directory / "samples.jsonl"
        self._atomic_write(aggregate, run.model_dump_json(indent=2))
        self._atomic_write(samples, "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in run.samples))
        return {"aggregate": aggregate, "samples": samples}

    def history(self) -> list[dict]:
        records = []
        if self.runs_root.is_dir():
            for path in self.runs_root.glob("*/aggregate.json"):
                try:
                    records.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        return sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)

    def clear_legacy_history(self) -> bool:
        path = self.data_root / "hardware-benchmarks.json"
        if not path.exists():
            return False
        path.unlink()
        return True
