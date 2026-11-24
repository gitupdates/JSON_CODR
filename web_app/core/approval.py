from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid7

from pydantic import Field

from web_app.core.adapters import CapabilityCall
from web_app.core.canonical import canonical_digest
from web_app.core.contracts import FrozenContract


ApprovalStatus = Literal["pending", "consumed", "rejected", "revoked"]


class ApprovalProposal(FrozenContract):
    proposal_id: str = Field(min_length=1)
    principal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    step_revision: int = Field(ge=1)
    call_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    project_fingerprint: str = Field(min_length=1)
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


class ApprovalLease(ApprovalProposal):
    status: Literal["consumed"] = "consumed"
    consumed_at: datetime


class ApprovalStore:
    def __init__(self, database: str | Path) -> None:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS approval_proposals (
                proposal_id TEXT PRIMARY KEY,
                principal TEXT NOT NULL,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                step_revision INTEGER NOT NULL,
                call_digest TEXT NOT NULL,
                project_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT
            )"""
        )
        self._lock = threading.RLock()

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _call_digest(call: CapabilityCall) -> str:
        return canonical_digest(call.model_dump(mode="json"))

    def propose(
        self,
        *,
        principal: str,
        project_id: str,
        task_id: str,
        step_id: str,
        step_revision: int,
        call: CapabilityCall,
        project_fingerprint: str,
        expires_at: datetime | None = None,
    ) -> ApprovalProposal:
        created_at = datetime.now(UTC)
        call_digest = self._call_digest(call)
        proposal = ApprovalProposal(
            proposal_id=f"approval:{call_digest[7:23]}:{uuid7()}",
            principal=principal,
            project_id=project_id,
            task_id=task_id,
            step_id=step_id,
            step_revision=step_revision,
            call_digest=call_digest,
            project_fingerprint=project_fingerprint,
            status="pending",
            created_at=created_at,
            expires_at=expires_at or created_at + timedelta(minutes=5),
        )
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO approval_proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal.proposal_id, proposal.principal, proposal.project_id,
                    proposal.task_id, proposal.step_id, proposal.step_revision,
                    proposal.call_digest, proposal.project_fingerprint, proposal.status,
                    proposal.created_at.isoformat(), proposal.expires_at.isoformat(), None,
                ),
            )
        return proposal

    def get(self, proposal_id: str) -> ApprovalProposal:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approval_proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        return self._proposal(row)

    def consume(
        self,
        proposal_id: str,
        *,
        principal: str,
        call: CapabilityCall,
        project_fingerprint: str,
        step_revision: int,
        now: datetime | None = None,
    ) -> ApprovalLease:
        consumed_at = now or datetime.now(UTC)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT * FROM approval_proposals WHERE proposal_id = ?", (proposal_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(proposal_id)
                proposal = self._proposal(row)
                if proposal.status != "pending":
                    reason = "already consumed" if proposal.status == "consumed" else proposal.status
                    raise PermissionError(f"approval is {reason}")
                if consumed_at >= proposal.expires_at:
                    raise PermissionError("approval is expired")
                if principal != proposal.principal:
                    raise PermissionError("approval principal does not match")
                if self._call_digest(call) != proposal.call_digest:
                    raise PermissionError("approval call does not match")
                if project_fingerprint != proposal.project_fingerprint:
                    raise PermissionError("approval project fingerprint does not match")
                if step_revision != proposal.step_revision:
                    raise PermissionError("approval step revision does not match")
                updated = self._connection.execute(
                    """UPDATE approval_proposals SET status = 'consumed', consumed_at = ?
                       WHERE proposal_id = ? AND status = 'pending'""",
                    (consumed_at.isoformat(), proposal_id),
                )
                if updated.rowcount != 1:
                    raise PermissionError("approval was already consumed")
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return ApprovalLease(**proposal.model_dump(exclude={"status", "consumed_at"}), consumed_at=consumed_at)

    def reject(self, proposal_id: str, *, principal: str) -> ApprovalProposal:
        proposal = self.get(proposal_id)
        if proposal.principal != principal:
            raise PermissionError("approval principal does not match")
        if proposal.status != "pending":
            raise PermissionError(f"approval is {proposal.status}")
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE approval_proposals SET status = 'rejected' WHERE proposal_id = ? AND status = 'pending'",
                (proposal_id,),
            )
        return self.get(proposal_id)

    def revoke_task(self, task_id: str) -> int:
        with self._lock, self._connection:
            result = self._connection.execute(
                "UPDATE approval_proposals SET status = 'revoked' WHERE task_id = ? AND status = 'pending'",
                (task_id,),
            )
        return result.rowcount

    @staticmethod
    def _proposal(row: sqlite3.Row) -> ApprovalProposal:
        return ApprovalProposal(
            proposal_id=row["proposal_id"], principal=row["principal"],
            project_id=row["project_id"], task_id=row["task_id"], step_id=row["step_id"],
            step_revision=int(row["step_revision"]), call_digest=row["call_digest"],
            project_fingerprint=row["project_fingerprint"], status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            consumed_at=None if row["consumed_at"] is None else datetime.fromisoformat(row["consumed_at"]),
        )
