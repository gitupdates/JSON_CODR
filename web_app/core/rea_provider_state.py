from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7


class RevisionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ReaCandidate:
    version: str
    integrity: str
    source: str
    state: str
    revision: int


@dataclass(frozen=True)
class ReaActivation:
    version: str
    generation: int
    previous_version: str | None


@dataclass(frozen=True)
class ReaLease:
    lease_id: str
    owner_id: str
    version: str
    generation: int


_TRANSITIONS = {
    "discovered": {"acquiring", "quarantined"},
    "acquiring": {"staged", "quarantined"},
    "staged": {"verifying", "quarantined"},
    "verifying": {"ready", "quarantined"},
    "ready": {"active", "quarantined"},
    "active": {"draining", "rolled_back"},
    "draining": {"active", "rolled_back"},
    "rolled_back": {"active", "quarantined"},
    "quarantined": {"acquiring", "verifying"},
}


class ReaProviderStore:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                version TEXT PRIMARY KEY, integrity TEXT NOT NULL, source TEXT NOT NULL,
                state TEXT NOT NULL, revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activations (
                generation INTEGER PRIMARY KEY, version TEXT NOT NULL REFERENCES candidates(version),
                previous_version TEXT, reason TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases (
                lease_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, version TEXT NOT NULL,
                generation INTEGER NOT NULL, released_at TEXT
            );
            CREATE TABLE IF NOT EXISTS provider_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL, payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def discover(self, version: str, *, integrity: str, source: str) -> ReaCandidate:
        if not version or not integrity or not source:
            raise ValueError("version, integrity, and source are required")
        with self._transaction():
            row = self._connection.execute("SELECT * FROM candidates WHERE version = ?", (version,)).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO candidates VALUES (?, ?, ?, 'discovered', 0)",
                    (version, integrity, source),
                )
                self._event("candidate.discovered", {"version": version, "integrity": integrity, "source": source})
            elif row["integrity"] != integrity or row["source"] != source:
                raise RevisionConflict("version already exists with a different package identity")
            return self.candidate(version)

    def candidate(self, version: str) -> ReaCandidate:
        row = self._connection.execute("SELECT * FROM candidates WHERE version = ?", (version,)).fetchone()
        if row is None:
            raise KeyError(version)
        return ReaCandidate(**dict(row))

    def transition(self, version: str, state: str, *, expected_revision: int) -> ReaCandidate:
        with self._transaction():
            return self._transition_unlocked(version, state, expected_revision)

    def active(self) -> ReaActivation | None:
        row = self._connection.execute("SELECT * FROM activations ORDER BY generation DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return ReaActivation(row["version"], row["generation"], row["previous_version"])

    def activate(self, version: str, *, expected_generation: int) -> ReaActivation:
        with self._transaction():
            current = self.active()
            generation = 0 if current is None else current.generation
            if generation != expected_generation:
                raise RevisionConflict(f"expected generation {expected_generation}, found {generation}")
            candidate = self.candidate(version)
            if candidate.state not in {"ready", "draining"}:
                raise ValueError(f"REA {version} is not ready for activation")
            if current is not None and current.version != version:
                previous = self.candidate(current.version)
                if previous.state == "active":
                    self._transition_unlocked(previous.version, "draining", previous.revision)
            if candidate.state != "active":
                candidate = self.candidate(version)
                self._transition_unlocked(version, "active", candidate.revision)
            next_generation = generation + 1
            previous_version = None if current is None else current.version
            self._connection.execute(
                "INSERT INTO activations VALUES (?, ?, ?, NULL, ?)",
                (next_generation, version, previous_version, datetime.now(UTC).isoformat()),
            )
            self._event("provider.activated", {"version": version, "generation": next_generation})
            return ReaActivation(version, next_generation, previous_version)

    def acquire_lease(self, owner_id: str) -> ReaLease:
        with self._transaction():
            active = self.active()
            if active is None:
                raise RuntimeError("REA has no active version")
            lease = ReaLease(str(uuid7()), owner_id, active.version, active.generation)
            self._connection.execute(
                "INSERT INTO leases VALUES (?, ?, ?, ?, NULL)",
                (lease.lease_id, lease.owner_id, lease.version, lease.generation),
            )
            self._event("lease.acquired", {"lease_id": lease.lease_id, "version": lease.version})
            return lease

    def release_lease(self, lease_id: str) -> None:
        with self._transaction():
            changed = self._connection.execute(
                "UPDATE leases SET released_at = ? WHERE lease_id = ? AND released_at IS NULL",
                (datetime.now(UTC).isoformat(), lease_id),
            )
            if changed.rowcount != 1:
                raise KeyError(lease_id)
            self._event("lease.released", {"lease_id": lease_id})

    def lease_count(self, version: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM leases WHERE version = ? AND released_at IS NULL", (version,)
        ).fetchone()
        return int(row["count"])

    def record_canary_failure(self, generation: int, reason: str) -> ReaActivation:
        with self._transaction():
            current = self.active()
            if current is None or current.generation != generation:
                actual = 0 if current is None else current.generation
                raise RevisionConflict(f"expected generation {generation}, found {actual}")
            if current.previous_version is None:
                raise RuntimeError("no previous REA version is available")
            failed = self.candidate(current.version)
            self._transition_unlocked(failed.version, "rolled_back", failed.revision)
            failed = self.candidate(failed.version)
            self._transition_unlocked(failed.version, "quarantined", failed.revision)
            previous = self.candidate(current.previous_version)
            self._transition_unlocked(previous.version, "active", previous.revision)
            next_generation = generation + 1
            self._connection.execute(
                "INSERT INTO activations VALUES (?, ?, ?, ?, ?)",
                (next_generation, previous.version, None, reason, datetime.now(UTC).isoformat()),
            )
            self._event("provider.rolled_back", {"version": current.version, "reason": reason})
            return ReaActivation(previous.version, next_generation, current.version)

    def recover(self) -> tuple[ReaCandidate, ...]:
        recovered = []
        with self._transaction():
            rows = self._connection.execute(
                "SELECT version FROM candidates WHERE state IN ('acquiring', 'verifying', 'activating') ORDER BY version"
            ).fetchall()
            for row in rows:
                candidate = self.candidate(row["version"])
                recovered.append(self._transition_unlocked(candidate.version, "quarantined", candidate.revision))
        return tuple(recovered)

    def versions(self) -> tuple[ReaCandidate, ...]:
        rows = self._connection.execute("SELECT version FROM candidates ORDER BY version").fetchall()
        return tuple(self.candidate(row["version"]) for row in rows)

    def removable_versions(self) -> tuple[str, ...]:
        active = self.active()
        protected = set()
        if active is not None:
            protected.add(active.version)
            if active.previous_version:
                protected.add(active.previous_version)
        rows = self._connection.execute(
            "SELECT DISTINCT version FROM leases WHERE released_at IS NULL"
        ).fetchall()
        protected.update(row["version"] for row in rows)
        return tuple(
            candidate.version for candidate in self.versions()
            if candidate.version not in protected and candidate.state in {"quarantined", "rolled_back"}
        )

    def _event(self, event_type: str, payload: dict) -> None:
        self._connection.execute(
            "INSERT INTO provider_events(event_id, event_type, payload_json, occurred_at) VALUES (?, ?, ?, ?)",
            (str(uuid7()), event_type, json.dumps(payload, sort_keys=True), datetime.now(UTC).isoformat()),
        )

    def _transition_unlocked(self, version: str, state: str, expected_revision: int) -> ReaCandidate:
        current = self.candidate(version)
        if current.revision != expected_revision:
            raise RevisionConflict(f"expected revision {expected_revision}, found {current.revision}")
        if state not in _TRANSITIONS.get(current.state, set()):
            raise ValueError(f"invalid REA transition: {current.state} -> {state}")
        updated = self._connection.execute(
            "UPDATE candidates SET state = ?, revision = revision + 1 WHERE version = ? AND revision = ?",
            (state, version, expected_revision),
        )
        if updated.rowcount != 1:
            raise RevisionConflict("candidate changed concurrently")
        self._event("candidate.transitioned", {"version": version, "from": current.state, "to": state})
        return self.candidate(version)

    def _transaction(self):
        return _Transaction(self._connection, self._lock)


class _Transaction:
    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:
        self.connection = connection
        self.lock = lock

    def __enter__(self):
        self.lock.acquire()
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exception_type, exception, traceback):
        self.connection.execute("ROLLBACK" if exception_type else "COMMIT")
        self.lock.release()
        return False
