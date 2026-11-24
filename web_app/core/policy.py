from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

from pydantic import Field

from web_app.core.adapters import CapabilityCall
from web_app.core.capability_registry import CapabilityRegistry
from web_app.core.canonical import canonical_digest
from web_app.core.contracts import FrozenContract


class PolicyEffect(str, Enum):
    allow = "allow"
    deny = "deny"
    require_approval = "require_approval"


class PolicyDecision(FrozenContract):
    effect: PolicyEffect
    reason: str = Field(min_length=1)


class PolicyService:
    def __init__(self, database: str | Path, *, registry: CapabilityRegistry | None = None) -> None:
        database_path = Path(database)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._registry = registry or CapabilityRegistry.default()
        self._migrate_grants()

    def _migrate_grants(self) -> None:
        required = {"principal", "project_id", "capability_id", "operation", "scope", "scope_key", "argument_digest", "expires_at"}
        legacy_columns = ("principal", "project_id", "capability_id", "operation", "scope", "scope_key")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                columns = {
                    row[1] for row in self._connection.execute("PRAGMA table_info(policy_grants)").fetchall()
                }
                if columns and not required.issubset(columns):
                    if not set(legacy_columns).issubset(columns):
                        raise ValueError("legacy policy grants have an unsupported schema")
                    self._connection.execute(
                        """CREATE TABLE IF NOT EXISTS policy_legacy_grants (
                            principal TEXT NOT NULL, project_id TEXT NOT NULL,
                            capability_id TEXT NOT NULL, operation TEXT NOT NULL,
                            scope TEXT NOT NULL, scope_key TEXT NOT NULL
                        )"""
                    )
                    self._connection.execute(
                        """INSERT INTO policy_legacy_grants
                        (principal, project_id, capability_id, operation, scope, scope_key)
                        SELECT principal, project_id, capability_id, operation, scope, scope_key
                        FROM policy_grants AS source
                        WHERE NOT EXISTS (
                            SELECT 1 FROM policy_legacy_grants AS legacy
                            WHERE legacy.principal = source.principal
                              AND legacy.project_id = source.project_id
                              AND legacy.capability_id = source.capability_id
                              AND legacy.operation = source.operation
                              AND legacy.scope = source.scope
                              AND legacy.scope_key = source.scope_key
                        )"""
                    )
                    self._connection.execute("DROP TABLE policy_grants")
                self._connection.execute(
                    """CREATE TABLE IF NOT EXISTS policy_grants (
                        principal TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        capability_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        scope_key TEXT NOT NULL,
                        argument_digest TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        PRIMARY KEY(principal, project_id, capability_id, operation, scope, scope_key, argument_digest)
                    )"""
                )
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def close(self) -> None:
        self._connection.close()

    def evaluate(
        self, principal: str, project_id: str, call: CapabilityCall, *, now: datetime | None = None,
        trusted_schedule_id: str | None = None,
    ) -> PolicyDecision:
        root = Path(call.project_root).resolve()
        if call.target_path is not None:
            target = Path(call.target_path)
            resolved_target = target.resolve() if target.is_absolute() else (root / target).resolve()
            if not resolved_target.is_relative_to(root):
                return PolicyDecision(effect=PolicyEffect.deny, reason="target escapes the approved project root")
        if call.mode.value == "brokered" and (
            call.privacy_boundary != call.approved_privacy_boundary
            or call.cost_boundary != call.approved_cost_boundary
        ):
            return PolicyDecision(effect=PolicyEffect.deny, reason="brokered route crosses an approved boundary")
        call = self._registry.normalize(call)
        if self._has_grant(principal, project_id, call, now=now, trusted_schedule_id=trusted_schedule_id):
            return PolicyDecision(effect=PolicyEffect.allow, reason="matching persistent grant")
        if self._registry.resolve(call.capability_id).autonomous:
            return PolicyDecision(effect=PolicyEffect.allow, reason="local bounded operation")
        return PolicyDecision(effect=PolicyEffect.require_approval, reason="registered operation requires approval")

    def grant(
        self, principal: str, project_id: str, call: CapabilityCall, *, scope: str,
        expires_at: datetime | None = None, schedule_id: str | None = None,
    ) -> None:
        call = self._registry.normalize(call)
        scope_key = self._scope_key(scope, schedule_id)
        expiry = expires_at or datetime.now(UTC) + timedelta(days=30)
        if expiry.tzinfo is None:
            raise ValueError("grant expiry must include a timezone")
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO policy_grants VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    principal, project_id, call.capability_id, call.operation, scope, scope_key,
                    self._argument_digest(call), expiry.astimezone(UTC).isoformat(),
                ),
            )

    def revoke(self, principal: str, project_id: str, call: CapabilityCall, *, scope: str) -> None:
        call = self._registry.normalize(call)
        scope_key = self._scope_key(scope, call.schedule_id if scope == "schedule" else None)
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM policy_grants WHERE principal=? AND project_id=? AND capability_id=? AND operation=? AND scope=? AND scope_key=? AND argument_digest=?",
                (principal, project_id, call.capability_id, call.operation, scope, scope_key, self._argument_digest(call)),
            )

    def _has_grant(
        self, principal: str, project_id: str, call: CapabilityCall, *, now: datetime | None = None,
        trusted_schedule_id: str | None = None,
    ) -> bool:
        with self._lock:
            rows = self._connection.execute(
                "SELECT scope, scope_key, expires_at FROM policy_grants WHERE principal=? AND project_id=? AND capability_id=? AND operation=? AND argument_digest=?",
                (principal, project_id, call.capability_id, call.operation, self._argument_digest(call)),
            ).fetchall()
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return any(
            datetime.fromisoformat(expires_at).astimezone(UTC) > current
            and (scope == "project" or (scope == "schedule" and key == (trusted_schedule_id or "")))
            for scope, key, expires_at in rows
        )

    @staticmethod
    def _argument_digest(call: CapabilityCall) -> str:
        return canonical_digest({
            "project_root": str(Path(call.project_root).resolve()),
            "target_path": call.target_path,
            "mode": call.mode.value,
            "privacy_boundary": call.privacy_boundary,
            "approved_privacy_boundary": call.approved_privacy_boundary,
            "cost_boundary": call.cost_boundary,
            "approved_cost_boundary": call.approved_cost_boundary,
            "schedule_id": call.schedule_id,
            "credential_refs": call.credential_refs,
            "arguments": call.arguments,
        })

    @staticmethod
    def _scope_key(scope: str, schedule_id: str | None) -> str:
        if scope == "project":
            return "*"
        if scope == "schedule" and schedule_id:
            return schedule_id
        raise ValueError("scope requires project or a concrete schedule")
