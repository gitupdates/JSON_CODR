from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from uuid import uuid7

from web_app.core.contracts import FrozenContract


class MemoryRecord(FrozenContract):
    record_id: str
    thread_id: str
    kind: str
    content: str
    source_ref: str


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
