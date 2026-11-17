from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CanonicalModelResult, CanonicalModelRun, ModelRunCreateRequest, ModelTiming, OriginalModelOutput


class RequestKeyConflict(ValueError):
    pass


class ModelRunStore:
    _TERMINAL_RESULTS = {"completed", "timeout", "failed", "cancelled", "unsupported"}

    def __init__(self, data_root: Path):
        self.root = Path(data_root).resolve() / "model-runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._request_index = self.root / "request-keys.json"

    def create(
        self,
        request: ModelRunCreateRequest,
        roster: list[str],
        request_key: str | None = None,
    ) -> CanonicalModelRun:
        stable_roster = list(dict.fromkeys(roster))
        key = request_key or request.request_key
        fingerprint = self._fingerprint(request, stable_roster)
        if key:
            existing = self.find_by_request_key(request.session_id, key, fingerprint)
            if existing is not None:
                return existing

        now = datetime.now(timezone.utc)
        run = CanonicalModelRun(
            run_id=uuid.uuid4().hex,
            session_id=request.session_id,
            mode="batch" if len(stable_roster) != 1 else "single",
            profile=request.profile,
            status="queued",
            prompt=request.prompt,
            roster=stable_roster,
            results=[
                CanonicalModelResult(
                    result_id=f"result-{model}",
                    requested_model=model,
                    effective_model=model,
                    status="queued",
                    timing=ModelTiming(started_at=now, duration_ms=0),
                )
                for model in stable_roster
            ],
            created_at=now,
        )
        self._write_run(run)
        if key:
            index = self._read_index()
            index[self._index_key(request.session_id, key)] = {
                "fingerprint": fingerprint,
                "run_id": run.run_id,
            }
            self._atomic_json(self._request_index, index)
        return run

    def get(self, run_id: str) -> CanonicalModelRun:
        path = self._run_dir(run_id) / "manifest.json"
        if not path.is_file():
            raise KeyError(run_id)
        return CanonicalModelRun.model_validate_json(path.read_text(encoding="utf-8"))

    def find_by_request_key(self, session_id: str, request_key: str, fingerprint: str) -> CanonicalModelRun | None:
        entry = self._read_index().get(self._index_key(session_id, request_key))
        if entry is None:
            return None
        if entry["fingerprint"] != fingerprint:
            raise RequestKeyConflict(f"request key {request_key!r} was already used with different input")
        try:
            return self.get(entry["run_id"])
        except KeyError:
            return None

    def append_original(
        self,
        run_id: str,
        result_id: str,
        original: OriginalModelOutput,
    ) -> OriginalModelOutput:
        run = self.get(run_id)
        if result_id not in {result.result_id for result in run.results}:
            raise KeyError(result_id)
        digest = original.digest.removeprefix("sha256:")
        original_path = self._run_dir(run_id) / "originals" / f"{digest}.json"
        self._atomic_json(original_path, original.model_dump(mode="json"))
        index_path = self._run_dir(run_id) / "original-index.json"
        index = self._read_json(index_path, {})
        index[result_id] = digest
        self._atomic_json(index_path, index)
        return original

    def get_original(self, run_id: str, result_id: str) -> OriginalModelOutput:
        index = self._read_json(self._run_dir(run_id) / "original-index.json", {})
        digest = index.get(result_id)
        if digest is None:
            raise KeyError(result_id)
        path = self._run_dir(run_id) / "originals" / f"{digest}.json"
        return OriginalModelOutput.model_validate_json(path.read_text(encoding="utf-8"))

    def update_result(self, run_id: str, result: CanonicalModelResult) -> CanonicalModelRun:
        run = self.get(run_id)
        results = list(run.results)
        position = next((index for index, item in enumerate(results) if item.result_id == result.result_id), None)
        if position is None:
            raise KeyError(result.result_id)
        if results[position].status in self._TERMINAL_RESULTS:
            return run
        if result.status == "completed" and (not result.original_output_id or not result.original_output_digest):
            raise ValueError("completed results require an original output id and digest")
        results[position] = result
        return self._persist_aggregate(run.model_copy(update={"results": results}))

    def request_cancel(self, run_id: str) -> CanonicalModelRun:
        run = self.get(run_id)
        now = datetime.now(timezone.utc)
        results = [
            item
            if item.status in self._TERMINAL_RESULTS
            else item.model_copy(
                update={
                    "status": "cancelled",
                    "timing": item.timing.model_copy(update={"completed_at": now}),
                }
            )
            for item in run.results
        ]
        return self._persist_aggregate(run.model_copy(update={"results": results}))

    def delete_session(self, session_id: str) -> None:
        for manifest in self.root.glob("*/manifest.json"):
            try:
                run = CanonicalModelRun.model_validate_json(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if run.session_id == session_id:
                target = manifest.parent.resolve()
                if target.parent != self.root:
                    raise ValueError("refusing to delete outside model-run root")
                shutil.rmtree(target)
        index = {
            key: value
            for key, value in self._read_index().items()
            if not key.startswith(f"{session_id}\0")
        }
        self._atomic_json(self._request_index, index)

    def _persist_aggregate(self, run: CanonicalModelRun) -> CanonicalModelRun:
        status = self._aggregate_status(run.results)
        now = datetime.now(timezone.utc)
        terminal = status in {"completed", "partial", "failed", "cancelled"}
        updated = run.model_copy(
            update={
                "status": status,
                "started_at": run.started_at or (now if status != "queued" else None),
                "completed_at": now if terminal else None,
            }
        )
        self._write_run(updated)
        return updated

    @classmethod
    def _aggregate_status(cls, results: list[CanonicalModelResult]) -> str:
        statuses = [item.status for item in results]
        if not statuses or all(status == "queued" for status in statuses):
            return "queued"
        if any(status in {"queued", "running"} for status in statuses):
            return "running"
        completed = sum(status == "completed" for status in statuses)
        if completed == len(statuses):
            return "completed"
        if completed:
            return "partial"
        if any(status == "cancelled" for status in statuses):
            return "cancelled"
        return "failed"

    def _write_run(self, run: CanonicalModelRun) -> None:
        self._atomic_json(self._run_dir(run.run_id) / "manifest.json", run.model_dump(mode="json"))

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or any(character not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_" for character in run_id):
            raise ValueError("invalid run id")
        return self.root / run_id

    @staticmethod
    def _fingerprint(request: ModelRunCreateRequest, roster: list[str]) -> str:
        payload = request.model_dump(mode="json", exclude={"request_key"})
        payload["roster"] = roster
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _index_key(session_id: str, request_key: str) -> str:
        return f"{session_id}\0{request_key}"

    def _read_index(self) -> dict[str, dict[str, str]]:
        return self._read_json(self._request_index, {})

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            temporary.write_text(data, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
