from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid7

from pydantic import Field

from web_app.core.contracts import FrozenContract


class MemoryRecord(FrozenContract):
    record_id: str
    thread_id: str
    kind: str
    content: str
    source_ref: str


class MemoryDraft(FrozenContract):
    user_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=65_536)
    source_refs: tuple[str, ...] = ()
    retain_details: bool = False
    idempotency_key: str = Field(min_length=1, max_length=256)


class CollectiveMemoryRecord(FrozenContract):
    memory_id: str
    user_id: str
    project_id: str
    thread_id: str
    task_id: str
    kind: str
    content: str
    source_refs: tuple[str, ...]
    retain_details: bool
    idempotency_key: str
    content_digest: str
    status: Literal["active", "revoked", "superseded"]
    created_at: datetime
    updated_at: datetime
    superseded_by: str | None = None
    status_reason: str | None = None


class MemoryPolicyError(ValueError):
    pass


_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?im)^\s*(?:password|passwd|token|api[_-]?key|secret)\s*=\s*\S+"),
)


def _looks_detailed(content: str) -> bool:
    lowered = content.lower()
    return "raw transcript:" in lowered or ("\nuser:" in lowered and "\nassistant:" in lowered)


def _validate_draft_policy(draft: MemoryDraft) -> None:
    if not draft.source_refs:
        raise MemoryPolicyError("collective memory requires evidence source references")
    if any(pattern.search(draft.content) for pattern in _SECRET_PATTERNS):
        raise MemoryPolicyError("collective memory rejected likely secret content")
    if _looks_detailed(draft.content) and not draft.retain_details:
        raise MemoryPolicyError("detailed retention requires explicit opt in")


class MemoryStore:
    def __init__(self, database: str | Path) -> None:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                record_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                source_ref TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                record_id UNINDEXED, thread_id UNINDEXED, content
            );
            CREATE TABLE IF NOT EXISTS collective_memory_records (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                source_refs_json TEXT NOT NULL,
                retain_details INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL,
                content_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                superseded_by TEXT,
                status_reason TEXT,
                UNIQUE(user_id, project_id, idempotency_key)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS collective_memory_fts USING fts5(
                memory_id UNINDEXED, user_id UNINDEXED, project_id UNINDEXED, content
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def add(self, thread_id: str, kind: str, content: str, *, source_ref: str) -> MemoryRecord:
        record = MemoryRecord(
            record_id=str(uuid7()), thread_id=thread_id, kind=kind, content=content, source_ref=source_ref
        )
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO memory_records VALUES (?, ?, ?, ?, ?)",
                (record.record_id, record.thread_id, record.kind, record.content, record.source_ref),
            )
            self._connection.execute(
                "INSERT INTO memory_fts VALUES (?, ?, ?)",
                (record.record_id, record.thread_id, record.content),
            )
        return record

    def replace_kind(self, thread_id: str, kind: str, content: str, *, source_ref: str) -> MemoryRecord:
        record = MemoryRecord(
            record_id=str(uuid7()), thread_id=thread_id, kind=kind, content=content, source_ref=source_ref
        )
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT record_id FROM memory_records WHERE thread_id = ? AND kind = ?",
                (thread_id, kind),
            ).fetchall()
            for row in rows:
                self._connection.execute("DELETE FROM memory_fts WHERE record_id = ?", (row["record_id"],))
            self._connection.execute(
                "DELETE FROM memory_records WHERE thread_id = ? AND kind = ?", (thread_id, kind)
            )
            self._connection.execute(
                "INSERT INTO memory_records VALUES (?, ?, ?, ?, ?)",
                (record.record_id, record.thread_id, record.kind, record.content, record.source_ref),
            )
            self._connection.execute(
                "INSERT INTO memory_fts VALUES (?, ?, ?)",
                (record.record_id, record.thread_id, record.content),
            )
        return record

    def list(self, thread_id: str) -> tuple[MemoryRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_records WHERE thread_id = ? ORDER BY rowid", (thread_id,)
            ).fetchall()
        return tuple(MemoryRecord.model_validate(dict(row)) for row in rows)

    def search(self, thread_id: str, query: str, limit: int = 20) -> tuple[MemoryRecord, ...]:
        if not query.strip():
            return self.list(thread_id)[:limit]
        with self._lock:
            rows = self._connection.execute(
                """SELECT records.* FROM memory_fts
                JOIN memory_records AS records USING(record_id)
                WHERE memory_fts MATCH ? AND memory_fts.thread_id = ?
                ORDER BY rank LIMIT ?""",
                (query, thread_id, limit),
            ).fetchall()
        return tuple(MemoryRecord.model_validate(dict(row)) for row in rows)

    def accept(self, draft: MemoryDraft) -> CollectiveMemoryRecord:
        _validate_draft_policy(draft)
        with self._lock:
            existing = self._connection.execute(
                """SELECT * FROM collective_memory_records
                WHERE user_id = ? AND project_id = ? AND idempotency_key = ?""",
                (draft.user_id, draft.project_id, draft.idempotency_key),
            ).fetchone()
            if existing is not None:
                return self._collective_record(existing)
        now = datetime.now(UTC)
        record = CollectiveMemoryRecord(
            memory_id=str(uuid7()),
            user_id=draft.user_id,
            project_id=draft.project_id,
            thread_id=draft.thread_id,
            task_id=draft.task_id,
            kind=draft.kind,
            content=draft.content,
            source_refs=draft.source_refs,
            retain_details=draft.retain_details,
            idempotency_key=draft.idempotency_key,
            content_digest="sha256:" + hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
            status="active",
            created_at=now,
            updated_at=now,
        )
        values = (
            record.memory_id, record.user_id, record.project_id, record.thread_id, record.task_id,
            record.kind, record.content, json.dumps(record.source_refs), int(record.retain_details),
            record.idempotency_key, record.content_digest, record.status,
            record.created_at.isoformat(), record.updated_at.isoformat(), None, None,
        )
        with self._lock, self._connection:
            try:
                self._connection.execute(
                    "INSERT INTO collective_memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                self._connection.execute(
                    "INSERT INTO collective_memory_fts VALUES (?, ?, ?, ?)",
                    (record.memory_id, record.user_id, record.project_id, record.content),
                )
            except sqlite3.IntegrityError:
                existing = self._connection.execute(
                    """SELECT * FROM collective_memory_records
                    WHERE user_id = ? AND project_id = ? AND idempotency_key = ?""",
                    (draft.user_id, draft.project_id, draft.idempotency_key),
                ).fetchone()
                if existing is None:
                    raise
                return self._collective_record(existing)
        return record

    def search_collective(
        self, user_id: str, project_id: str, query: str, limit: int = 20
    ) -> tuple[CollectiveMemoryRecord, ...]:
        if not query.strip():
            return self.export_collective(user_id, project_id)[:limit]
        fts_query = '"' + query.strip().replace('"', '""') + '"'
        with self._lock:
            rows = self._connection.execute(
                """SELECT records.* FROM collective_memory_fts
                JOIN collective_memory_records AS records USING(memory_id)
                WHERE collective_memory_fts MATCH ?
                  AND collective_memory_fts.user_id = ?
                  AND collective_memory_fts.project_id = ?
                  AND records.status = 'active'
                ORDER BY rank LIMIT ?""",
                (fts_query, user_id, project_id, limit),
            ).fetchall()
        return tuple(self._collective_record(row) for row in rows)

    def export_collective(
        self, user_id: str, project_id: str, *, include_inactive: bool = False
    ) -> tuple[CollectiveMemoryRecord, ...]:
        status_clause = "" if include_inactive else " AND status = 'active'"
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM collective_memory_records
                WHERE user_id = ? AND project_id = ?""" + status_clause + " ORDER BY rowid",
                (user_id, project_id),
            ).fetchall()
        return tuple(self._collective_record(row) for row in rows)

    def revoke(
        self, memory_id: str, *, user_id: str, project_id: str, reason: str
    ) -> CollectiveMemoryRecord:
        return self._set_inactive(
            memory_id, user_id=user_id, project_id=project_id, status="revoked", reason=reason
        )

    def supersede(self, memory_id: str, replacement: MemoryDraft) -> CollectiveMemoryRecord:
        with self._lock:
            old = self._scoped_collective(memory_id, replacement.user_id, replacement.project_id)
        if old.status != "active":
            raise MemoryPolicyError("only active collective memory can be superseded")
        new = self.accept(replacement)
        self._set_inactive(
            memory_id,
            user_id=replacement.user_id,
            project_id=replacement.project_id,
            status="superseded",
            reason="replaced by newer verified memory",
            superseded_by=new.memory_id,
        )
        return new

    def _set_inactive(
        self,
        memory_id: str,
        *,
        user_id: str,
        project_id: str,
        status: Literal["revoked", "superseded"],
        reason: str,
        superseded_by: str | None = None,
    ) -> CollectiveMemoryRecord:
        with self._lock, self._connection:
            self._scoped_collective(memory_id, user_id, project_id)
            self._connection.execute(
                """UPDATE collective_memory_records
                SET status = ?, status_reason = ?, superseded_by = ?, updated_at = ?
                WHERE memory_id = ? AND user_id = ? AND project_id = ?""",
                (status, reason, superseded_by, datetime.now(UTC).isoformat(), memory_id, user_id, project_id),
            )
            self._connection.execute(
                "DELETE FROM collective_memory_fts WHERE memory_id = ?", (memory_id,)
            )
            row = self._connection.execute(
                "SELECT * FROM collective_memory_records WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return self._collective_record(row)

    def _scoped_collective(
        self, memory_id: str, user_id: str, project_id: str
    ) -> CollectiveMemoryRecord:
        row = self._connection.execute(
            """SELECT * FROM collective_memory_records
            WHERE memory_id = ? AND user_id = ? AND project_id = ?""",
            (memory_id, user_id, project_id),
        ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return self._collective_record(row)

    @staticmethod
    def _collective_record(row: sqlite3.Row) -> CollectiveMemoryRecord:
        values = dict(row)
        values["source_refs"] = tuple(json.loads(values.pop("source_refs_json")))
        values["retain_details"] = bool(values["retain_details"])
        return CollectiveMemoryRecord.model_validate(values)
