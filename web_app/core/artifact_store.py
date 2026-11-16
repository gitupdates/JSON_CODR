from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import BinaryIO, Mapping

from pydantic import Field, JsonValue, field_validator

from web_app.core.contracts import FrozenContract, TaskId
from web_app.core.canonical import canonical_digest


_SENSITIVE_KEYS = {"api_key", "authorization", "cookie", "credential", "password", "secret", "token"}


class ArtifactMetadata(FrozenContract):
    task_id: TaskId | None = None
    media_type: str = Field(min_length=1)
    metadata: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def redact_metadata(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return _redact(value)


class ArtifactRecord(FrozenContract):
    artifact_id: str
    digest: str
    size: int = Field(ge=0)
    media_type: str
    metadata_digest: str
    metadata: Mapping[str, JsonValue] = Field(default_factory=dict)


class RetentionPolicy(FrozenContract):
    max_unreferenced: int = Field(default=0, ge=0)


class ArtifactStore:
    def __init__(self, root: str | Path, database: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        database_path = Path(database)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                digest TEXT NOT NULL UNIQUE,
                size INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                metadata_digest TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_artifacts (
                task_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
                PRIMARY KEY(task_id, artifact_id)
            );
            """
        )
        self._connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self._connection.close()

    def put(self, stream: BinaryIO, metadata: ArtifactMetadata) -> ArtifactRecord:
        digest = hashlib.sha256()
        size = 0
        handle, temporary_name = tempfile.mkstemp(dir=self._root)
        try:
            with os.fdopen(handle, "wb") as output:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            digest_value = f"sha256:{digest.hexdigest()}"
            artifact_id = digest_value
            target = self._path(digest.hexdigest())
            target.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connection:
                row = self._connection.execute(
                    "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()
                if row is None:
                    os.replace(temporary_name, target)
                    temporary_name = ""
                    self._connection.execute(
                        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            artifact_id,
                            digest_value,
                            size,
                            metadata.media_type,
                            canonical_digest(dict(metadata.metadata)),
                            json.dumps(dict(metadata.metadata), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                        ),
                    )
                if metadata.task_id is not None:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO task_artifacts VALUES (?, ?)", (metadata.task_id, artifact_id)
                    )
            return self._record(artifact_id)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)

    def open(self, artifact_id: str) -> BinaryIO:
        record = self._record(artifact_id)
        return self._path(record.digest.removeprefix("sha256:")).open("rb")

    def prune(self, policy: RetentionPolicy) -> tuple[str, ...]:
        with self._lock, self._connection:
            rows = self._connection.execute(
                """SELECT artifact_id, digest FROM artifacts
                   WHERE artifact_id NOT IN (SELECT artifact_id FROM task_artifacts)
                   ORDER BY artifact_id"""
            ).fetchall()
            remove = rows[: max(0, len(rows) - policy.max_unreferenced)]
            for row in remove:
                self._connection.execute("DELETE FROM artifacts WHERE artifact_id = ?", (row["artifact_id"],))
                self._path(row["digest"].removeprefix("sha256:")).unlink(missing_ok=True)
            return tuple(row["artifact_id"] for row in remove)

    def export_manifest(self, task_id: str) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT a.* FROM artifacts a JOIN task_artifacts t ON a.artifact_id = t.artifact_id
                   WHERE t.task_id = ? ORDER BY a.artifact_id""",
                (task_id,),
            ).fetchall()
            return [self._row_record(row).model_dump(mode="json") for row in rows]

    def _record(self, artifact_id: str) -> ArtifactRecord:
        with self._lock:
            row = self._connection.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
            if row is None:
                raise FileNotFoundError(artifact_id)
            return self._row_record(row)

    def _row_record(self, row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            digest=row["digest"],
            size=row["size"],
            media_type=row["media_type"],
            metadata_digest=row["metadata_digest"],
            metadata=json.loads(row["metadata_json"]),
        )

    def _path(self, digest: str) -> Path:
        return self._root / digest[:2] / digest[2:]


def _redact(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _redact(item) for key, item in value.items() if key.casefold() not in _SENSITIVE_KEYS}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value
