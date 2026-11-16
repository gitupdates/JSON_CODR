from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import TaskCommand, TaskEvent, TaskEventDraft, TaskRecord, TaskStatus


class ConcurrencyConflict(RuntimeError):
    pass


class IntegrityViolation(RuntimeError):
    pass


_EVENT_STATUSES = {
    "task.started": TaskStatus.running,
    "task.completed": TaskStatus.completed,
    "task.failed": TaskStatus.failed,
    "task.cancelled": TaskStatus.cancelled,
    "task.cancel_requested": TaskStatus.cancel_requested,
    "task.interrupted": TaskStatus.interrupted,
}


class TaskStore:
    def __init__(self, database: str | Path) -> None:
        self._database = Path(database)
        self._database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._database, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                command_id TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                parent_task_id TEXT REFERENCES tasks(task_id),
                status TEXT NOT NULL,
                command_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_events (
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL,
                PRIMARY KEY(task_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS tasks_parent_idx ON tasks(parent_task_id, task_id);
            """
        )

    def close(self) -> None:
        self._connection.close()

    def create(self, command: TaskCommand) -> TaskRecord:
        with self._transaction():
            existing = self._connection.execute(
                "SELECT task_id FROM tasks WHERE command_id = ?", (command.command_id,)
            ).fetchone()
            if existing is not None:
                if existing["task_id"] != command.task_id:
                    raise ConcurrencyConflict("idempotency key belongs to another task")
                return self._get_unlocked(command.task_id)
            self._connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    command.task_id,
                    command.command_id,
                    command.thread_id,
                    command.project_id,
                    command.parent_task_id,
                    TaskStatus.pending.value,
                    command.model_dump_json(),
                ),
            )
            self._append_unlocked(
                command.task_id,
                TaskEventDraft(
                    event_type="task.created",
                    payload={"command_type": command.command_type},
                    causation_id=command.command_id,
                ),
            )
            return self._get_unlocked(command.task_id)

    def append(
        self,
        task_id: str,
        event: TaskEventDraft,
        *,
        expected_version: int | None = None,
    ) -> TaskEvent:
        with self._transaction():
            current = self._current_sequence(task_id)
            if expected_version is not None and current != expected_version:
                raise ConcurrencyConflict(f"expected version {expected_version}, found {current}")
            return self._append_unlocked(task_id, event)

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            return self._get_unlocked(task_id)

    def events(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        with self._lock:
            return self._events_unlocked(task_id, after_sequence)

    def children(self, task_id: str) -> tuple[TaskRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT task_id FROM tasks WHERE parent_task_id = ? ORDER BY task_id", (task_id,)
            ).fetchall()
            return tuple(self._get_unlocked(row["task_id"]) for row in rows)

    def request_cancel(self, task_id: str) -> TaskRecord:
        with self._transaction():
            record = self._get_unlocked(task_id)
            if record.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.interrupted}:
                return record
            self._append_unlocked(task_id, TaskEventDraft(event_type="task.cancel_requested"))
            return self._get_unlocked(task_id)

    def recover_interrupted(self) -> tuple[TaskRecord, ...]:
        with self._transaction():
            rows = self._connection.execute(
                "SELECT task_id FROM tasks WHERE status = ? ORDER BY task_id", (TaskStatus.running.value,)
            ).fetchall()
            recovered = []
            for row in rows:
                self._append_unlocked(row["task_id"], TaskEventDraft(event_type="task.interrupted"))
                recovered.append(self._get_unlocked(row["task_id"]))
            return tuple(recovered)

    def _append_unlocked(self, task_id: str, draft: TaskEventDraft) -> TaskEvent:
        if self._connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
            raise KeyError(task_id)
        current_sequence = self._current_sequence(task_id)
        previous = self._connection.execute(
            "SELECT event_json FROM task_events WHERE task_id = ? AND sequence = ?",
            (task_id, current_sequence),
        ).fetchone()
        previous_digest = None if previous is None else TaskEvent.model_validate_json(previous["event_json"]).event_digest
        event = TaskEvent(
            **draft.model_dump(mode="python"),
            event_id=uuid7(),
            task_id=task_id,
            sequence=current_sequence + 1,
            source="json-codr://core/task-store",
            subject=f"tasks/{task_id}",
            occurred_at=datetime.now(UTC),
            previous_event_digest=previous_digest,
            event_digest="sha256:" + "0" * 64,
        )
        event = event.model_copy(update={"event_digest": _event_digest(event)})
        self._connection.execute(
            "INSERT INTO task_events VALUES (?, ?, ?, ?)",
            (task_id, event.sequence, str(event.event_id), event.model_dump_json()),
        )
        status = _EVENT_STATUSES.get(event.event_type)
        if status is not None:
            self._connection.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status.value, task_id))
        return event

    def _get_unlocked(self, task_id: str) -> TaskRecord:
        row = self._connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return TaskRecord(
            task_id=row["task_id"],
            thread_id=row["thread_id"],
            project_id=row["project_id"],
            parent_task_id=row["parent_task_id"],
            status=row["status"],
            events=self._events_unlocked(task_id),
        )

    def _events_unlocked(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        rows = self._connection.execute(
            "SELECT event_json FROM task_events WHERE task_id = ? AND sequence > ? ORDER BY sequence",
            (task_id, after_sequence),
        ).fetchall()
        events = tuple(TaskEvent.model_validate_json(row["event_json"]) for row in rows)
        previous = None
        if after_sequence >= 0:
            prior_row = self._connection.execute(
                "SELECT event_json FROM task_events WHERE task_id = ? AND sequence = ?", (task_id, after_sequence)
            ).fetchone()
            previous = None if prior_row is None else TaskEvent.model_validate_json(prior_row["event_json"]).event_digest
        for event in events:
            if event.previous_event_digest != previous or event.event_digest != _event_digest(event):
                raise IntegrityViolation(f"event chain verification failed for {task_id} at sequence {event.sequence}")
            previous = event.event_digest
        return events

    def _current_sequence(self, task_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), -1) AS sequence FROM task_events WHERE task_id = ?", (task_id,)
        ).fetchone()
        return int(row["sequence"])

    def _transaction(self):
        return _Transaction(self._connection, self._lock)


class _Transaction:
    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:
        self._connection = connection
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire()
        self._connection.execute("BEGIN IMMEDIATE")

    def __exit__(self, error_type, error, traceback) -> None:
        try:
            self._connection.execute("ROLLBACK" if error_type else "COMMIT")
        finally:
            self._lock.release()


def _event_digest(event: TaskEvent) -> str:
    material = event.model_dump(mode="json", exclude={"event_digest"})
    return canonical_digest(material)
