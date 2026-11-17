from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid7

from pydantic import Field, model_validator

from web_app.core.contracts import Digest, FrozenContract


class ComponentScope(str, Enum):
    global_ = "global"
    project = "project"


class ComponentSource(str, Enum):
    git = "git"
    local = "local"
    archive = "archive"
    python = "python"
    node = "node"
    mcp = "mcp"
    executable = "executable"


class ComponentRequest(FrozenContract):
    source_kind: ComponentSource
    source: str = Field(min_length=1)
    requested_version: str | None = None
    scope: ComponentScope = ComponentScope.global_
    project_id: str | None = None
    activation: bool = True

    @model_validator(mode="after")
    def validate_scope(self) -> "ComponentRequest":
        if self.scope is ComponentScope.project and not self.project_id:
            raise ValueError("project scope requires project_id")
        if self.scope is ComponentScope.global_ and self.project_id is not None:
            raise ValueError("global scope cannot include project_id")
        return self


class ComponentPlan(FrozenContract):
    plan_id: str
    component_id: str
    source_kind: ComponentSource
    source: str
    requested_version: str | None = None
    scope: ComponentScope
    project_id: str | None = None
    content_digest: Digest
    effects: tuple[str, ...] = ()
    executable: bool = False
    entry_points: tuple[str, ...] = ()
    runtime_kind: str = "resource"


class ComponentGeneration(FrozenContract):
    component_id: str
    generation: int = Field(ge=1)
    state: str
    plan_id: str
    content_digest: Digest
    evidence_digest: Digest | None = None
    reason: str | None = None
    runtime_root: str | None = None
    executable: bool = False
    entry_points: tuple[str, ...] = ()
    runtime_kind: str = "resource"


class ComponentActivation(FrozenContract):
    component_id: str
    generation: int = Field(ge=1)
    scope: ComponentScope
    project_id: str | None = None
    previous_generation: int | None = None


class ComponentLease(FrozenContract):
    lease_id: str
    component_id: str
    generation: int
    project_id: str


class ComponentRegistryEvent(FrozenContract):
    sequence: int
    event_id: UUID
    event_type: str
    payload: dict
    occurred_at: datetime


class ComponentRegistry:
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
            CREATE TABLE IF NOT EXISTS component_plans (
                plan_id TEXT PRIMARY KEY, component_id TEXT NOT NULL, request_json TEXT NOT NULL,
                content_digest TEXT NOT NULL, effects_json TEXT NOT NULL, executable INTEGER NOT NULL,
                entry_points_json TEXT NOT NULL, runtime_kind TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS component_generations (
                component_id TEXT NOT NULL, generation INTEGER NOT NULL, state TEXT NOT NULL,
                plan_id TEXT NOT NULL REFERENCES component_plans(plan_id), content_digest TEXT NOT NULL,
                evidence_digest TEXT, reason TEXT, runtime_root TEXT, executable INTEGER NOT NULL,
                entry_points_json TEXT NOT NULL, runtime_kind TEXT NOT NULL, quarantine_expires_at TEXT,
                created_at TEXT NOT NULL, PRIMARY KEY(component_id, generation)
            );
            CREATE TABLE IF NOT EXISTS component_activations (
                component_id TEXT NOT NULL, scope TEXT NOT NULL, project_key TEXT NOT NULL,
                generation INTEGER NOT NULL, previous_generation INTEGER, created_at TEXT NOT NULL,
                PRIMARY KEY(component_id, scope, project_key),
                FOREIGN KEY(component_id, generation) REFERENCES component_generations(component_id, generation)
            );
            CREATE TABLE IF NOT EXISTS component_leases (
                lease_id TEXT PRIMARY KEY, component_id TEXT NOT NULL, generation INTEGER NOT NULL,
                project_id TEXT NOT NULL, released_at TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS component_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL, payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def plan(
        self,
        request: ComponentRequest,
        *,
        content_digest: str | None = None,
        effects: tuple[str, ...] = (),
        executable: bool = False,
        entry_points: tuple[str, ...] = (),
        runtime_kind: str = "resource",
    ) -> ComponentPlan:
        canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        component_id = "component-" + hashlib.sha256(
            f"{request.source_kind.value}:{request.source}".encode("utf-8")
        ).hexdigest()[:16]
        digest = content_digest or "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        plan_material = json.dumps(
            {
                "request": json.loads(canonical),
                "content_digest": digest,
                "effects": effects,
                "executable": executable,
                "entry_points": entry_points,
                "runtime_kind": runtime_kind,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_id = "plan-" + hashlib.sha256(plan_material.encode("utf-8")).hexdigest()[:24]
        plan = ComponentPlan(
            plan_id=plan_id,
            component_id=component_id,
            source_kind=request.source_kind,
            source=request.source,
            requested_version=request.requested_version,
            scope=request.scope,
            project_id=request.project_id,
            content_digest=digest,
            effects=effects,
            executable=executable,
            entry_points=entry_points,
            runtime_kind=runtime_kind,
        )
        with self._transaction():
            self._connection.execute(
                "INSERT OR IGNORE INTO component_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan.plan_id,
                    plan.component_id,
                    canonical,
                    plan.content_digest,
                    json.dumps(plan.effects),
                    int(plan.executable),
                    json.dumps(plan.entry_points),
                    plan.runtime_kind,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._event("component.plan.created", {"plan_id": plan.plan_id, "component_id": component_id})
        return plan

    def stage(self, plan: ComponentPlan, *, runtime_root: str | None = None) -> ComponentGeneration:
        with self._transaction():
            row = self._connection.execute(
                "SELECT COALESCE(MAX(generation), 0) + 1 AS generation FROM component_generations WHERE component_id = ?",
                (plan.component_id,),
            ).fetchone()
            generation = int(row["generation"])
            self._connection.execute(
                "INSERT INTO component_generations VALUES (?, ?, 'staged', ?, ?, NULL, NULL, ?, ?, ?, ?, NULL, ?)",
                (
                    plan.component_id,
                    generation,
                    plan.plan_id,
                    plan.content_digest,
                    runtime_root,
                    int(plan.executable),
                    json.dumps(plan.entry_points),
                    plan.runtime_kind,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._event("component.generation.staged", {"component_id": plan.component_id, "generation": generation})
            return self.generation(plan.component_id, generation)

    def record_probe(
        self,
        component_id: str,
        generation: int,
        *,
        succeeded: bool,
        evidence_digest: str,
        reason: str | None = None,
        runtime_root: str | None = None,
    ) -> ComponentGeneration:
        state = "verified" if succeeded else "quarantined"
        expires = None if succeeded else (datetime.now(UTC) + timedelta(days=7)).isoformat()
        with self._transaction():
            changed = self._connection.execute(
                """UPDATE component_generations
                   SET state = ?, evidence_digest = ?, reason = ?, runtime_root = COALESCE(?, runtime_root),
                       quarantine_expires_at = ?
                   WHERE component_id = ? AND generation = ? AND state = 'staged'""",
                (state, evidence_digest, reason, runtime_root, expires, component_id, generation),
            )
            if changed.rowcount != 1:
                raise ValueError("component generation is not staged")
            self._event(
                "component.probe.completed",
                {"component_id": component_id, "generation": generation, "succeeded": succeeded},
            )
            return self.generation(component_id, generation)

    def generation(self, component_id: str, generation: int) -> ComponentGeneration:
        row = self._connection.execute(
            "SELECT * FROM component_generations WHERE component_id = ? AND generation = ?",
            (component_id, generation),
        ).fetchone()
        if row is None:
            raise KeyError((component_id, generation))
        return self._generation(row)

    def request_for_plan(self, plan_id: str) -> ComponentRequest:
        row = self._connection.execute(
            "SELECT request_json FROM component_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return ComponentRequest.model_validate(json.loads(row["request_json"]))

    def generations(self, component_id: str | None = None) -> tuple[ComponentGeneration, ...]:
        if component_id is None:
            rows = self._connection.execute(
                "SELECT * FROM component_generations ORDER BY component_id, generation"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM component_generations WHERE component_id = ? ORDER BY generation", (component_id,)
            ).fetchall()
        return tuple(self._generation(row) for row in rows)

    def activate(
        self,
        component_id: str,
        generation: int,
        *,
        scope: ComponentScope,
        project_id: str | None = None,
    ) -> ComponentActivation:
        if scope is ComponentScope.project and not project_id:
            raise ValueError("project activation requires project_id")
        candidate = self.generation(component_id, generation)
        if candidate.state != "verified":
            raise PermissionError("component generation has not been verified")
        project_key = project_id or ""
        with self._transaction():
            current = self._connection.execute(
                "SELECT generation FROM component_activations WHERE component_id = ? AND scope = ? AND project_key = ?",
                (component_id, scope.value, project_key),
            ).fetchone()
            previous = None if current is None else int(current["generation"])
            self._connection.execute(
                """INSERT INTO component_activations VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(component_id, scope, project_key) DO UPDATE SET
                   previous_generation = component_activations.generation,
                   generation = excluded.generation, created_at = excluded.created_at""",
                (component_id, scope.value, project_key, generation, previous, datetime.now(UTC).isoformat()),
            )
            self._event(
                "component.activated",
                {"component_id": component_id, "generation": generation, "scope": scope.value, "project_id": project_id},
            )
        return ComponentActivation(
            component_id=component_id,
            generation=generation,
            scope=scope,
            project_id=project_id,
            previous_generation=previous,
        )

    def resolve(self, component_id: str, project_id: str) -> ComponentActivation | None:
        project = self._activation(component_id, ComponentScope.project, project_id)
        return project or self._activation(component_id, ComponentScope.global_, None)

    def activations(self, project_id: str | None = None) -> tuple[ComponentActivation, ...]:
        rows = self._connection.execute("SELECT component_id FROM component_activations GROUP BY component_id").fetchall()
        result = []
        for row in rows:
            activation = self.resolve(row["component_id"], project_id or "")
            if activation is not None:
                result.append(activation)
        return tuple(result)

    def disable(self, component_id: str, *, scope: ComponentScope, project_id: str | None = None) -> None:
        project_key = project_id or ""
        with self._transaction():
            changed = self._connection.execute(
                "DELETE FROM component_activations WHERE component_id = ? AND scope = ? AND project_key = ?",
                (component_id, scope.value, project_key),
            )
            if changed.rowcount != 1:
                raise KeyError(component_id)
            self._event(
                "component.disabled", {"component_id": component_id, "scope": scope.value, "project_id": project_id}
            )

    def rollback(
        self, component_id: str, *, scope: ComponentScope, project_id: str | None = None
    ) -> ComponentActivation:
        project_key = project_id or ""
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM component_activations WHERE component_id = ? AND scope = ? AND project_key = ?",
                (component_id, scope.value, project_key),
            ).fetchone()
            if row is None or row["previous_generation"] is None:
                raise RuntimeError("no previous verified generation is available")
            current = int(row["generation"])
            previous = int(row["previous_generation"])
            self._connection.execute(
                "UPDATE component_activations SET generation = ?, previous_generation = ? WHERE component_id = ? AND scope = ? AND project_key = ?",
                (previous, current, component_id, scope.value, project_key),
            )
            self._event("component.rolled_back", {"component_id": component_id, "generation": previous})
        return ComponentActivation(
            component_id=component_id,
            generation=previous,
            scope=scope,
            project_id=project_id,
            previous_generation=current,
        )

    def acquire_lease(self, component_id: str, project_id: str) -> ComponentLease:
        activation = self.resolve(component_id, project_id)
        if activation is None:
            raise KeyError(component_id)
        lease = ComponentLease(
            lease_id=str(uuid7()),
            component_id=component_id,
            generation=activation.generation,
            project_id=project_id,
        )
        with self._transaction():
            self._connection.execute(
                "INSERT INTO component_leases VALUES (?, ?, ?, ?, NULL, ?)",
                (lease.lease_id, lease.component_id, lease.generation, lease.project_id, datetime.now(UTC).isoformat()),
            )
            self._event("component.lease.acquired", lease.model_dump(mode="json"))
        return lease

    def release_lease(self, lease_id: str) -> None:
        with self._transaction():
            changed = self._connection.execute(
                "UPDATE component_leases SET released_at = ? WHERE lease_id = ? AND released_at IS NULL",
                (datetime.now(UTC).isoformat(), lease_id),
            )
            if changed.rowcount != 1:
                raise KeyError(lease_id)
            self._event("component.lease.released", {"lease_id": lease_id})

    def remove(self, component_id: str, generation: int) -> None:
        with self._transaction():
            leased = self._connection.execute(
                "SELECT 1 FROM component_leases WHERE component_id = ? AND generation = ? AND released_at IS NULL",
                (component_id, generation),
            ).fetchone()
            if leased is not None:
                raise PermissionError("component generation is leased")
            active = self._connection.execute(
                "SELECT 1 FROM component_activations WHERE component_id = ? AND generation = ?",
                (component_id, generation),
            ).fetchone()
            if active is not None:
                raise PermissionError("component generation is active")
            changed = self._connection.execute(
                "DELETE FROM component_generations WHERE component_id = ? AND generation = ?",
                (component_id, generation),
            )
            if changed.rowcount != 1:
                raise KeyError((component_id, generation))
            self._event("component.generation.removed", {"component_id": component_id, "generation": generation})

    def recover(self) -> tuple[ComponentGeneration, ...]:
        recovered = []
        with self._transaction():
            rows = self._connection.execute(
                "SELECT component_id, generation FROM component_generations WHERE state IN ('staging', 'staged', 'installing')"
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    """UPDATE component_generations SET state = 'quarantined', reason = 'installation interrupted',
                       quarantine_expires_at = ? WHERE component_id = ? AND generation = ?""",
                    (
                        (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                        row["component_id"],
                        row["generation"],
                    ),
                )
                self._event(
                    "component.generation.recovered",
                    {"component_id": row["component_id"], "generation": row["generation"]},
                )
                recovered.append(self.generation(row["component_id"], int(row["generation"])))
        return tuple(recovered)

    def events(self) -> tuple[ComponentRegistryEvent, ...]:
        rows = self._connection.execute("SELECT * FROM component_events ORDER BY sequence").fetchall()
        return tuple(
            ComponentRegistryEvent(
                sequence=int(row["sequence"]),
                event_id=UUID(row["event_id"]),
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in rows
        )

    def _activation(
        self, component_id: str, scope: ComponentScope, project_id: str | None
    ) -> ComponentActivation | None:
        row = self._connection.execute(
            "SELECT * FROM component_activations WHERE component_id = ? AND scope = ? AND project_key = ?",
            (component_id, scope.value, project_id or ""),
        ).fetchone()
        if row is None:
            return None
        return ComponentActivation(
            component_id=row["component_id"],
            generation=int(row["generation"]),
            scope=ComponentScope(row["scope"]),
            project_id=project_id,
            previous_generation=row["previous_generation"],
        )

    def _generation(self, row: sqlite3.Row) -> ComponentGeneration:
        return ComponentGeneration(
            component_id=row["component_id"],
            generation=int(row["generation"]),
            state=row["state"],
            plan_id=row["plan_id"],
            content_digest=row["content_digest"],
            evidence_digest=row["evidence_digest"],
            reason=row["reason"],
            runtime_root=row["runtime_root"],
            executable=bool(row["executable"]),
            entry_points=tuple(json.loads(row["entry_points_json"])),
            runtime_kind=row["runtime_kind"],
        )

    def _event(self, event_type: str, payload: dict) -> None:
        self._connection.execute(
            "INSERT INTO component_events(event_id, event_type, payload_json, occurred_at) VALUES (?, ?, ?, ?)",
            (str(uuid7()), event_type, json.dumps(payload, sort_keys=True), datetime.now(UTC).isoformat()),
        )

    @contextmanager
    def _transaction(self):
        self._lock.acquire()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")
        finally:
            self._lock.release()
