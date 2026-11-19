from __future__ import annotations

import sqlite3
import threading
from enum import Enum
from pathlib import Path

from pydantic import Field

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import FrozenContract


class PolicyEffect(str, Enum):
    allow = "allow"
    deny = "deny"
    require_approval = "require_approval"


class PolicyDecision(FrozenContract):
    effect: PolicyEffect
    reason: str = Field(min_length=1)


_AUTOMATIC_OPERATIONS = {"read", "search", "discover", "generate"}
_SENSITIVE_OPERATIONS = {"network", "install", "commit", "push", "destructive"}


class PolicyService:
    def __init__(self, database: str | Path) -> None:
        database_path = Path(database)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS policy_grants (
                principal TEXT NOT NULL,
                project_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                scope TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                PRIMARY KEY(principal, project_id, capability_id, operation, scope, scope_key)
            )"""
        )

    def close(self) -> None:
        self._connection.close()

    def evaluate(self, principal: str, project_id: str, call: CapabilityCall) -> PolicyDecision:
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
        if self._has_grant(principal, project_id, call):
            return PolicyDecision(effect=PolicyEffect.allow, reason="matching persistent grant")
        if call.operation in _AUTOMATIC_OPERATIONS:
            return PolicyDecision(effect=PolicyEffect.allow, reason="local bounded operation")
        if call.operation in _SENSITIVE_OPERATIONS:
            return PolicyDecision(effect=PolicyEffect.require_approval, reason="sensitive operation requires approval")
        return PolicyDecision(effect=PolicyEffect.require_approval, reason="operation has no automatic policy")

    def grant(self, principal: str, project_id: str, call: CapabilityCall, *, scope: str) -> None:
        scope_key = self._scope_key(call, scope)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO policy_grants VALUES (?, ?, ?, ?, ?, ?)",
                (principal, project_id, call.capability_id, call.operation, scope, scope_key),
            )

    def revoke(self, principal: str, project_id: str, call: CapabilityCall, *, scope: str) -> None:
        scope_key = self._scope_key(call, scope)
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM policy_grants WHERE principal=? AND project_id=? AND capability_id=? AND operation=? AND scope=? AND scope_key=?",
                (principal, project_id, call.capability_id, call.operation, scope, scope_key),
            )

    def _has_grant(self, principal: str, project_id: str, call: CapabilityCall) -> bool:
        with self._lock:
            rows = self._connection.execute(
                "SELECT scope, scope_key FROM policy_grants WHERE principal=? AND project_id=? AND capability_id=? AND operation=?",
                (principal, project_id, call.capability_id, call.operation),
            ).fetchall()
        return any(scope == "project" or (scope == "schedule" and key == (call.schedule_id or "")) for scope, key in rows)

    @staticmethod
    def _scope_key(call: CapabilityCall, scope: str) -> str:
        if scope == "project":
            return "*"
        if scope == "schedule" and call.schedule_id:
            return call.schedule_id
        raise ValueError("scope requires project or a concrete schedule")
