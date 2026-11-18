from __future__ import annotations

import sqlite3
import threading
from enum import Enum
from pathlib import Path

from pydantic import Field

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import FrozenContract
from web_app.core.canonical import canonical_digest
from web_app.models import ExecutionPolicySettings


class PolicyEffect(str, Enum):
    allow = "allow"
    deny = "deny"
    require_approval = "require_approval"
    strong_confirmation = "strong_confirmation"


class PolicyDecision(FrozenContract):
    effect: PolicyEffect
    reason: str = Field(min_length=1)


class PolicySnapshot(FrozenContract):
    preset: str
    project_id: str
    overrides: tuple[tuple[str, str], ...] = ()
    requires_plan_approval: bool = True
    canonical_digest: str


_AUTOMATIC_OPERATIONS = {"read", "search", "test", "bounded_edit", "session", "interrupt", "close", "generate"}
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

    def snapshot(self, settings: ExecutionPolicySettings, project_id: str) -> PolicySnapshot:
        effective = dict(settings.global_overrides)
        effective.update(settings.project_overrides.get(project_id, {}))
        material = {
            "preset": settings.preset,
            "project_id": project_id,
            "overrides": sorted(effective.items()),
            "requires_plan_approval": True,
        }
        return PolicySnapshot(
            preset=settings.preset,
            project_id=project_id,
            overrides=tuple(sorted(effective.items())),
            canonical_digest=canonical_digest(material),
        )

    def evaluate(
        self,
        principal: str,
        project_id: str,
        call: CapabilityCall,
        *,
        snapshot: PolicySnapshot | None = None,
        task_denials: frozenset[str] = frozenset(),
    ) -> PolicyDecision:
        root = Path(call.project_root).resolve()
        if call.target_path is not None and not Path(call.target_path).resolve().is_relative_to(root):
            return PolicyDecision(effect=PolicyEffect.deny, reason="target escapes the approved project root")
        if call.mode.value == "brokered" and (
            call.privacy_boundary != call.approved_privacy_boundary
            or call.cost_boundary != call.approved_cost_boundary
        ):
            return PolicyDecision(effect=PolicyEffect.deny, reason="brokered route crosses an approved boundary")
        if snapshot is not None:
            if call.operation == "destructive":
                return PolicyDecision(
                    effect=PolicyEffect.strong_confirmation,
                    reason="destructive operation requires strong confirmation",
                )
            if call.capability_id in task_denials:
                return PolicyDecision(effect=PolicyEffect.deny, reason="capability denied for this task")
            override = dict(snapshot.overrides).get(call.capability_id)
            if override is not None:
                effects = {
                    "allow": PolicyEffect.allow,
                    "ask": PolicyEffect.require_approval,
                    "deny": PolicyEffect.deny,
                }
                return PolicyDecision(effect=effects[override], reason="configured capability override")
            automatic = {
                "balanced": {"read", "search", "session", "interrupt", "close", "generate"},
                "strict": set(),
                "autonomous": {
                    "read", "search", "session", "interrupt", "close", "generate",
                    "bounded_edit", "test",
                },
            }
            if call.operation in automatic.get(snapshot.preset, set()):
                return PolicyDecision(effect=PolicyEffect.allow, reason=f"{snapshot.preset} preset allows operation")
            return PolicyDecision(
                effect=PolicyEffect.require_approval,
                reason=f"{snapshot.preset} preset requires approval",
            )
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
