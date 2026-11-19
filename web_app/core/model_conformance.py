from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import Digest, FrozenContract


Classification = Literal["native_verified", "broker_verified", "chat_only"]


class ConformanceEvidence(FrozenContract):
    model: str
    model_digest: Digest
    ollama_version: str
    runtime_version: str
    planner_contract_version: str
    catalog_digest: Digest
    adapter_digests: tuple[Digest, ...]
    passed: bool
    evidence: tuple[str, ...]

    @property
    def evidence_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class ModelConformanceRecord(FrozenContract):
    model: str
    classification: Classification
    evidence_digest: Digest
    evidence: ConformanceEvidence
    verified_at: datetime


class ModelConformanceStore:
    def __init__(self, database: str | Path) -> None:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS model_conformance (model TEXT PRIMARY KEY, classification TEXT NOT NULL, evidence_digest TEXT NOT NULL, evidence_json TEXT NOT NULL, verified_at TEXT NOT NULL)"
        )

    def close(self) -> None:
        self._connection.close()

    def record(self, evidence: ConformanceEvidence, *, classification: Classification) -> ModelConformanceRecord:
        if classification != "chat_only" and not evidence.passed:
            raise ValueError("verified model classification requires passing evidence")
        record = ModelConformanceRecord(
            model=evidence.model, classification=classification,
            evidence_digest=evidence.evidence_digest, evidence=evidence,
            verified_at=datetime.now(UTC),
        )
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO model_conformance VALUES (?, ?, ?, ?, ?)",
                (record.model, record.classification, record.evidence_digest,
                 evidence.model_dump_json(), record.verified_at.isoformat()),
            )
        return record

    def get(self, model: str) -> ModelConformanceRecord | None:
        row = self._connection.execute("SELECT * FROM model_conformance WHERE model = ?", (model,)).fetchone()
        if row is None:
            return None
        evidence = ConformanceEvidence.model_validate_json(row["evidence_json"])
        return ModelConformanceRecord(
            model=row["model"], classification=row["classification"],
            evidence_digest=row["evidence_digest"], evidence=evidence,
            verified_at=datetime.fromisoformat(row["verified_at"]),
        )

    def is_current(self, model: str, evidence: ConformanceEvidence) -> bool:
        record = self.get(model)
        return record is not None and record.evidence_digest == evidence.evidence_digest
