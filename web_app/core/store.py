from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import (
    EffectIntent,
    EffectIntentDraft,
    EffectState,
    PlanRevision,
    TaskCommand,
    TaskEvent,
    TaskEventDraft,
    TaskRecord,
    TaskStatus,
    RuntimeHeartbeat,
    TelemetryRecord,
)


class ConcurrencyConflict(RuntimeError):
    pass


class IntegrityViolation(RuntimeError):
    pass


class InvalidEffectTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class PlannedStepReservation:
    step_event: TaskEvent
    child: TaskRecord
    created: bool


@dataclass(frozen=True)
class EffectReservation:
    event: TaskEvent
    effect: EffectIntent
    created: bool


_EVENT_STATUSES = {
    "task.started": TaskStatus.running,
    "task.completed": TaskStatus.completed,
    "task.failed": TaskStatus.failed,
    "task.cancelled": TaskStatus.cancelled,
    "task.cancel_requested": TaskStatus.cancel_requested,
    "task.interrupted": TaskStatus.interrupted,
}

_EFFECT_TRANSITIONS = {
    EffectState.pending: {EffectState.leased, EffectState.cancel_requested, EffectState.failed},
    EffectState.leased: {EffectState.running, EffectState.pending, EffectState.failed, EffectState.cancel_requested, EffectState.unknown_requires_reconciliation},
    EffectState.running: {EffectState.succeeded, EffectState.failed, EffectState.cancel_requested, EffectState.unknown_requires_reconciliation},
    EffectState.cancel_requested: {EffectState.cancelled, EffectState.unknown_requires_reconciliation},
    EffectState.unknown_requires_reconciliation: {EffectState.succeeded, EffectState.failed},
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
                global_sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL,
                PRIMARY KEY(task_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS planned_steps (
                parent_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                plan_id TEXT NOT NULL,
                plan_revision INTEGER NOT NULL,
                step_id TEXT NOT NULL,
                child_task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE CASCADE,
                child_command_id TEXT NOT NULL,
                step_event_sequence INTEGER NOT NULL,
                PRIMARY KEY(parent_task_id, plan_id, plan_revision, step_id)
            );
            CREATE TABLE IF NOT EXISTS plan_revisions (
                parent_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                plan_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(parent_task_id, plan_id, revision)
            );
            CREATE TABLE IF NOT EXISTS effects (
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                effect_id TEXT NOT NULL,
                event_sequence INTEGER NOT NULL,
                draft_json TEXT NOT NULL,
                effect_json TEXT NOT NULL,
                PRIMARY KEY(task_id, effect_id),
                UNIQUE(task_id, event_sequence)
            );
            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                depends_on_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                PRIMARY KEY(task_id, depends_on_task_id),
                CHECK(task_id <> depends_on_task_id)
            );
            CREATE TABLE IF NOT EXISTS telemetry (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                telemetry_id TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_heartbeats (
                runtime_id TEXT PRIMARY KEY,
                pid INTEGER NOT NULL,
                status TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tasks_parent_idx ON tasks(parent_task_id, task_id);
            CREATE INDEX IF NOT EXISTS effects_state_idx ON effects(task_id, json_extract(effect_json, '$.state'));
            CREATE INDEX IF NOT EXISTS task_dependencies_ready_idx ON task_dependencies(task_id, depends_on_task_id);
            """
        )
        self._migrate_event_order()

    def close(self) -> None:
        self._connection.close()

    def set_dependencies(self, task_id: str, dependencies: tuple[str, ...]) -> None:
        if task_id in dependencies or len(dependencies) != len(set(dependencies)):
            raise ValueError("task dependencies must be unique and cannot reference self")
        with self._transaction():
            self._get_unlocked(task_id)
            for dependency in dependencies:
                self._get_unlocked(dependency)
            self._connection.execute("DELETE FROM task_dependencies WHERE task_id = ?", (task_id,))
            self._connection.executemany(
                "INSERT INTO task_dependencies VALUES (?, ?)",
                ((task_id, dependency) for dependency in dependencies),
            )

    def ready_tasks(self) -> tuple[TaskRecord, ...]:
        with self._transaction():
            rows = self._connection.execute(
                """SELECT task_id FROM tasks candidate
                   WHERE status = ?
                   AND NOT EXISTS (
                       SELECT 1 FROM task_dependencies dependency
                       JOIN tasks required ON required.task_id = dependency.depends_on_task_id
                       WHERE dependency.task_id = candidate.task_id AND required.status <> ?
                   )
                   ORDER BY rowid""",
                (TaskStatus.pending.value, TaskStatus.completed.value),
            ).fetchall()
            return tuple(self._get_unlocked(row["task_id"]) for row in rows)

    def record_telemetry(self, kind: str, payload: dict) -> TelemetryRecord:
        if not kind:
            raise ValueError("telemetry kind is required")
        with self._transaction():
            telemetry_id = f"telemetry:{uuid7()}"
            observed_at = datetime.now(UTC)
            cursor = self._connection.execute(
                "INSERT INTO telemetry(telemetry_id, kind, payload_json, observed_at) VALUES (?, ?, ?, ?)",
                (telemetry_id, kind, json.dumps(payload, separators=(",", ":"), sort_keys=True), observed_at.isoformat()),
            )
            return TelemetryRecord(
                telemetry_id=telemetry_id,
                sequence=int(cursor.lastrowid),
                kind=kind,
                payload=payload,
                observed_at=observed_at,
            )

    def telemetry(self, after_sequence: int = 0) -> tuple[TelemetryRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM telemetry WHERE sequence > ? ORDER BY sequence", (after_sequence,)
            ).fetchall()
            return tuple(TelemetryRecord(
                telemetry_id=row["telemetry_id"],
                sequence=int(row["sequence"]),
                kind=row["kind"],
                payload=json.loads(row["payload_json"]),
                observed_at=datetime.fromisoformat(row["observed_at"]),
            ) for row in rows)

    def record_heartbeat(self, runtime_id: str, pid: int, status: str) -> RuntimeHeartbeat:
        observed_at = datetime.now(UTC)
        heartbeat = RuntimeHeartbeat(
            runtime_id=runtime_id,
            pid=pid,
            status=status,
            observed_at=observed_at,
        )
        with self._transaction():
            self._connection.execute(
                """INSERT INTO runtime_heartbeats VALUES (?, ?, ?, ?)
                   ON CONFLICT(runtime_id) DO UPDATE SET
                   pid=excluded.pid, status=excluded.status, observed_at=excluded.observed_at""",
                (runtime_id, pid, status, observed_at.isoformat()),
            )
        return heartbeat

    def runtime_heartbeat(
        self,
        runtime_id: str,
        *,
        now: datetime | None = None,
        stale_after: timedelta = timedelta(seconds=60),
    ) -> RuntimeHeartbeat:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runtime_heartbeats WHERE runtime_id = ?", (runtime_id,)
            ).fetchone()
        if row is None:
            raise KeyError(runtime_id)
        observed_at = datetime.fromisoformat(row["observed_at"])
        stale = (now or datetime.now(UTC)) - observed_at > stale_after
        return RuntimeHeartbeat(
            runtime_id=row["runtime_id"],
            pid=int(row["pid"]),
            status=row["status"],
            observed_at=observed_at,
            stale=stale,
        )

    def runtime_heartbeats(
        self,
        *,
        now: datetime | None = None,
        stale_after: timedelta = timedelta(seconds=60),
    ) -> tuple[RuntimeHeartbeat, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT runtime_id FROM runtime_heartbeats ORDER BY runtime_id"
            ).fetchall()
        return tuple(
            self.runtime_heartbeat(row["runtime_id"], now=now, stale_after=stale_after)
            for row in rows
        )

    def create(self, command: TaskCommand) -> TaskRecord:
        with self._transaction():
            return self._create_unlocked(command)

    def save_plan_revision(
        self,
        parent_task_id: str,
        plan: PlanRevision,
        *,
        expected_revision: int | None = None,
    ) -> PlanRevision:
        with self._transaction():
            self._get_unlocked(parent_task_id)
            row = self._connection.execute(
                "SELECT MAX(revision) AS revision FROM plan_revisions WHERE parent_task_id = ? AND plan_id = ?",
                (parent_task_id, plan.plan_id),
            ).fetchone()
            current = None if row is None or row["revision"] is None else int(row["revision"])
            if expected_revision != current:
                raise ConcurrencyConflict(f"expected plan revision {expected_revision}, found {current}")
            expected_next = 1 if current is None else current + 1
            if plan.revision != expected_next:
                raise ValueError(f"next plan revision must be {expected_next}")
            self._connection.execute(
                "INSERT INTO plan_revisions VALUES (?, ?, ?, ?, ?)",
                (parent_task_id, plan.plan_id, plan.revision, plan.model_dump_json(), datetime.now(UTC).isoformat()),
            )
        return plan

    def plan_revisions(self, parent_task_id: str, plan_id: str) -> tuple[PlanRevision, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT plan_json FROM plan_revisions WHERE parent_task_id = ? AND plan_id = ? ORDER BY revision",
                (parent_task_id, plan_id),
            ).fetchall()
        return tuple(PlanRevision.model_validate_json(row["plan_json"]) for row in rows)

    def latest_plan(self, parent_task_id: str, plan_id: str) -> PlanRevision | None:
        revisions = self.plan_revisions(parent_task_id, plan_id)
        return None if not revisions else revisions[-1]

    def plan_step_and_create_child(
        self,
        parent_task_id: str,
        plan_id: str,
        plan_revision: int,
        step_id: str,
        child_command: TaskCommand,
        *,
        expected_version: int | None = None,
    ) -> PlannedStepReservation:
        with self._transaction():
            existing = self._connection.execute(
                """SELECT child_task_id, child_command_id, step_event_sequence
                   FROM planned_steps
                   WHERE parent_task_id = ? AND plan_id = ? AND plan_revision = ? AND step_id = ?""",
                (parent_task_id, plan_id, plan_revision, step_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["child_task_id"] != child_command.task_id
                    or existing["child_command_id"] != child_command.command_id
                ):
                    raise ConcurrencyConflict("planned step is already reserved for another child command")
                event = self._event_unlocked(parent_task_id, int(existing["step_event_sequence"]))
                return PlannedStepReservation(event, self._get_unlocked(child_command.task_id), False)
            parent = self._get_unlocked(parent_task_id)
            if child_command.parent_task_id != parent_task_id:
                raise ValueError("planned child must reference its parent task")
            if child_command.thread_id != parent.thread_id or child_command.project_id != parent.project_id:
                raise ValueError("planned child must remain in the parent thread and project")
            current = self._current_sequence(parent_task_id)
            if expected_version is not None and current != expected_version:
                raise ConcurrencyConflict(f"expected version {expected_version}, found {current}")
            step_event = self._append_unlocked(
                parent_task_id,
                TaskEventDraft(
                    event_type="agent.step_planned",
                    payload={
                        "plan_id": plan_id,
                        "plan_revision": plan_revision,
                        "step_id": step_id,
                        "child_task_id": child_command.task_id,
                        "child_command_id": child_command.command_id,
                    },
                    causation_id=child_command.command_id,
                ),
            )
            child = self._create_unlocked(child_command)
            self._connection.execute(
                "INSERT INTO planned_steps VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    parent_task_id, plan_id, plan_revision, step_id, child_command.task_id,
                    child_command.command_id, step_event.sequence,
                ),
            )
            return PlannedStepReservation(step_event, child, True)

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

    def append_with_effect(
        self,
        task_id: str,
        event: TaskEventDraft,
        effect: EffectIntentDraft,
        *,
        expected_version: int | None = None,
    ) -> EffectReservation:
        with self._transaction():
            existing = self._connection.execute(
                "SELECT event_sequence, draft_json, effect_json FROM effects WHERE task_id = ? AND effect_id = ?",
                (task_id, effect.effect_id),
            ).fetchone()
            if existing is not None:
                if EffectIntentDraft.model_validate_json(existing["draft_json"]) != effect:
                    raise ConcurrencyConflict("effect id is already reserved for another intent")
                return EffectReservation(
                    event=self._event_unlocked(task_id, int(existing["event_sequence"])),
                    effect=EffectIntent.model_validate_json(existing["effect_json"]),
                    created=False,
                )
            current = self._current_sequence(task_id)
            if expected_version is not None and current != expected_version:
                raise ConcurrencyConflict(f"expected version {expected_version}, found {current}")
            persisted_event = self._append_unlocked(task_id, event)
            now = datetime.now(UTC)
            persisted_effect = EffectIntent(
                **effect.model_dump(mode="python"),
                task_id=task_id,
                state=EffectState.pending,
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
            self._connection.execute(
                "INSERT INTO effects VALUES (?, ?, ?, ?, ?)",
                (
                    task_id,
                    effect.effect_id,
                    persisted_event.sequence,
                    effect.model_dump_json(),
                    persisted_effect.model_dump_json(),
                ),
            )
            return EffectReservation(persisted_event, persisted_effect, True)

    def effect(self, task_id: str, effect_id: str) -> EffectIntent:
        with self._lock:
            row = self._connection.execute(
                "SELECT effect_json FROM effects WHERE task_id = ? AND effect_id = ?", (task_id, effect_id)
            ).fetchone()
            if row is None:
                raise KeyError((task_id, effect_id))
            return EffectIntent.model_validate_json(row["effect_json"])

    def effects(
        self, task_id: str, states: set[EffectState] | None = None
    ) -> tuple[EffectIntent, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT effect_json FROM effects WHERE task_id = ? ORDER BY rowid", (task_id,)
            ).fetchall()
            effects = tuple(EffectIntent.model_validate_json(row["effect_json"]) for row in rows)
            return effects if states is None else tuple(effect for effect in effects if effect.state in states)

    def transition_effect(
        self,
        task_id: str,
        effect_id: str,
        state: EffectState,
        *,
        expected_state: EffectState,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> EffectIntent:
        with self._transaction():
            return self._transition_effect_unlocked(
                task_id,
                effect_id,
                state,
                expected_state=expected_state,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
            )

    def lease_pending_effects(
        self,
        *,
        owner: str,
        limit: int,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> tuple[EffectIntent, ...]:
        if limit < 1:
            raise ValueError("effect lease limit must be positive")
        if lease_duration <= timedelta(0):
            raise ValueError("effect lease duration must be positive")
        leased_at = now or datetime.now(UTC)
        with self._transaction():
            rows = self._connection.execute(
                """SELECT task_id, effect_id FROM effects
                   WHERE json_extract(effect_json, '$.state') = ?
                   ORDER BY rowid LIMIT ?""",
                (EffectState.pending.value, limit),
            ).fetchall()
            return tuple(
                self._transition_effect_unlocked(
                    row["task_id"],
                    row["effect_id"],
                    EffectState.leased,
                    expected_state=EffectState.pending,
                    lease_owner=owner,
                    lease_expires_at=leased_at + lease_duration,
                    updated_at=leased_at,
                )
                for row in rows
            )

    def recover_expired_effect_leases(self, *, now: datetime | None = None) -> tuple[EffectIntent, ...]:
        observed_at = now or datetime.now(UTC)
        with self._transaction():
            rows = self._connection.execute(
                """SELECT task_id, effect_id, effect_json FROM effects
                   WHERE json_extract(effect_json, '$.state') IN (?, ?)
                   ORDER BY rowid""",
                (EffectState.leased.value, EffectState.running.value),
            ).fetchall()
            recovered = []
            for row in rows:
                intent = EffectIntent.model_validate_json(row["effect_json"])
                if intent.lease_expires_at is None or intent.lease_expires_at > observed_at:
                    continue
                recovered.append(self._transition_effect_unlocked(
                    row["task_id"],
                    row["effect_id"],
                    EffectState.unknown_requires_reconciliation,
                    expected_state=intent.state,
                    updated_at=observed_at,
                ))
            return tuple(recovered)

    def reconcile_effect(self, task_id: str, effect_id: str, outcome: str) -> EffectIntent:
        if outcome == "still_unknown":
            return self.effect(task_id, effect_id)
        if outcome not in {"succeeded", "not_applied"}:
            raise ValueError("reconciliation outcome must be succeeded, not_applied, or still_unknown")
        target = EffectState.succeeded if outcome == "succeeded" else EffectState.failed
        return self.transition_effect(
            task_id,
            effect_id,
            target,
            expected_state=EffectState.unknown_requires_reconciliation,
        )

    def _transition_effect_unlocked(
        self,
        task_id: str,
        effect_id: str,
        state: EffectState,
        *,
        expected_state: EffectState,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> EffectIntent:
        row = self._connection.execute(
            "SELECT effect_json FROM effects WHERE task_id = ? AND effect_id = ?", (task_id, effect_id)
        ).fetchone()
        if row is None:
            raise KeyError((task_id, effect_id))
        current = EffectIntent.model_validate_json(row["effect_json"])
        if current.state is not expected_state:
            raise ConcurrencyConflict(f"expected effect state {expected_state.value}, found {current.state.value}")
        if state not in _EFFECT_TRANSITIONS.get(current.state, set()):
            raise InvalidEffectTransition(f"cannot transition effect from {current.state.value} to {state.value}")
        updated = current.model_copy(
            update={
                "state": state,
                "attempt_count": current.attempt_count + (1 if state is EffectState.leased else 0),
                "lease_owner": lease_owner if state is EffectState.leased else current.lease_owner,
                "lease_expires_at": lease_expires_at if state is EffectState.leased else current.lease_expires_at,
                "updated_at": updated_at or datetime.now(UTC),
            }
        )
        self._connection.execute(
            "UPDATE effects SET effect_json = ? WHERE task_id = ? AND effect_id = ?",
            (updated.model_dump_json(), task_id, effect_id),
        )
        return updated

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            return self._get_unlocked(task_id)

    def command(self, task_id: str) -> TaskCommand:
        with self._lock:
            row = self._connection.execute(
                "SELECT command_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            return TaskCommand.model_validate_json(row["command_json"])

    def events(self, task_id: str, after_sequence: int = -1) -> tuple[TaskEvent, ...]:
        with self._lock:
            return self._events_unlocked(task_id, after_sequence)

    def children(self, task_id: str) -> tuple[TaskRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT task_id FROM tasks WHERE parent_task_id = ? ORDER BY task_id", (task_id,)
            ).fetchall()
            return tuple(self._get_unlocked(row["task_id"]) for row in rows)

    def for_thread(self, thread_id: str) -> tuple[TaskRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT task_id FROM tasks WHERE thread_id = ? ORDER BY rowid", (thread_id,)
            ).fetchall()
            return tuple(self._get_unlocked(row["task_id"]) for row in rows)

    def for_project(self, project_id: str) -> tuple[TaskRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT task_id FROM tasks WHERE project_id = ? ORDER BY rowid", (project_id,)
            ).fetchall()
            return tuple(self._get_unlocked(row["task_id"]) for row in rows)

    def thread_events(self, thread_id: str, after_global_sequence: int = -1) -> tuple[TaskEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT event_json FROM task_events
                   JOIN tasks USING(task_id)
                   WHERE thread_id = ? AND global_sequence > ?
                   ORDER BY global_sequence""",
                (thread_id, after_global_sequence),
            ).fetchall()
            return tuple(TaskEvent.model_validate_json(row["event_json"]) for row in rows)

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
        if draft.event_type == "task.completed":
            unresolved = self._connection.execute(
                "SELECT 1 FROM effects WHERE task_id = ? AND json_extract(effect_json, '$.state') = ? LIMIT 1",
                (task_id, EffectState.unknown_requires_reconciliation.value),
            ).fetchone()
            if unresolved is not None:
                raise InvalidEffectTransition("task completion is blocked by an unknown effect")
        current_sequence = self._current_sequence(task_id)
        previous = self._connection.execute(
            "SELECT event_json FROM task_events WHERE task_id = ? AND sequence = ?",
            (task_id, current_sequence),
        ).fetchone()
        previous_digest = None if previous is None else TaskEvent.model_validate_json(previous["event_json"]).event_digest
        global_sequence = self._current_global_sequence() + 1
        event = TaskEvent(
            **draft.model_dump(mode="python"),
            event_id=uuid7(),
            task_id=task_id,
            sequence=current_sequence + 1,
            global_sequence=global_sequence,
            source="json-codr://core/task-store",
            subject=f"tasks/{task_id}",
            occurred_at=datetime.now(UTC),
            previous_event_digest=previous_digest,
            event_digest="sha256:" + "0" * 64,
        )
        event = event.model_copy(update={"event_digest": _event_digest(event)})
        self._connection.execute(
            "INSERT INTO task_events(task_id, sequence, global_sequence, event_id, event_json) VALUES (?, ?, ?, ?, ?)",
            (task_id, event.sequence, event.global_sequence, str(event.event_id), event.model_dump_json()),
        )
        status = _EVENT_STATUSES.get(event.event_type)
        if status is not None:
            self._connection.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status.value, task_id))
        return event

    def _create_unlocked(self, command: TaskCommand) -> TaskRecord:
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
                command.task_id, command.command_id, command.thread_id, command.project_id,
                command.parent_task_id, TaskStatus.pending.value, command.model_dump_json(),
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

    def _event_unlocked(self, task_id: str, sequence: int) -> TaskEvent:
        row = self._connection.execute(
            "SELECT event_json FROM task_events WHERE task_id = ? AND sequence = ?", (task_id, sequence)
        ).fetchone()
        if row is None:
            raise IntegrityViolation("planned step points to a missing event")
        return TaskEvent.model_validate_json(row["event_json"])

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

    def _current_global_sequence(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(global_sequence), -1) AS sequence FROM task_events"
        ).fetchone()
        return int(row["sequence"])

    def _migrate_event_order(self) -> None:
        columns = {
            row["name"] for row in self._connection.execute("PRAGMA table_info(task_events)").fetchall()
        }
        if "global_sequence" not in columns:
            self._connection.execute("ALTER TABLE task_events ADD COLUMN global_sequence INTEGER")
        rows = self._connection.execute(
            "SELECT task_id, sequence, event_json FROM task_events ORDER BY rowid"
        ).fetchall()
        previous_digests: dict[str, str | None] = {}
        for global_sequence, row in enumerate(rows):
            event_data = json.loads(row["event_json"])
            event_data["global_sequence"] = global_sequence
            event_data["previous_event_digest"] = previous_digests.get(row["task_id"])
            migrated = TaskEvent.model_validate(event_data)
            migrated = migrated.model_copy(update={"event_digest": _event_digest(migrated)})
            previous_digests[row["task_id"]] = migrated.event_digest
            self._connection.execute(
                "UPDATE task_events SET global_sequence = ?, event_json = ? WHERE task_id = ? AND sequence = ?",
                (global_sequence, migrated.model_dump_json(), row["task_id"], row["sequence"]),
            )
        self._connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS task_events_global_sequence_idx ON task_events(global_sequence)"
        )

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
