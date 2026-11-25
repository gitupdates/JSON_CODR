from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from collections.abc import Sequence
from typing import Literal
from uuid import uuid7

from pydantic import Field

from web_app.core.adapters import CapabilityCall
from web_app.core.canonical import canonical_digest
from web_app.core.contracts import FrozenContract


ApprovalStatus = Literal["pending", "consumed", "rejected", "revoked"]
EnvelopeStatus = Literal["pending", "approved", "consumed", "rejected", "revoked"]
EnvelopeCallStatus = Literal["pending", "reserved", "consumed"]
EnvelopeOutcome = Literal["completed", "failed"]


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


class ApprovalEnvelopeCall(FrozenContract):
    ordinal: int = Field(ge=0)
    call_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capability_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    target_path: str | None = None
    status: EnvelopeCallStatus = "pending"
    reserved_at: datetime | None = None
    consumed_at: datetime | None = None
    before_fingerprint: str | None = None
    after_fingerprint: str | None = None
    outcome: EnvelopeOutcome | None = None


class ApprovalEnvelope(FrozenContract):
    envelope_id: str = Field(min_length=1)
    principal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_revision: int = Field(ge=1)
    project_fingerprint: str = Field(min_length=1)
    current_project_fingerprint: str = Field(min_length=1)
    calls: tuple[ApprovalEnvelopeCall, ...] = Field(min_length=1, max_length=32)
    status: EnvelopeStatus
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None = None
    consumed_at: datetime | None = None
    receipt_digest: str | None = None


class ApprovalEnvelopeLease(FrozenContract):
    envelope_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    principal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_revision: int = Field(ge=1)
    call_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    project_fingerprint: str = Field(min_length=1)
    reserved_at: datetime
    expires_at: datetime


class ApprovalEnvelopeReceipt(FrozenContract):
    envelope_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_revision: int = Field(ge=1)
    call_digests: tuple[str, ...] = Field(min_length=1)
    outcomes: tuple[EnvelopeOutcome, ...] = Field(min_length=1)
    initial_project_fingerprint: str = Field(min_length=1)
    final_project_fingerprint: str = Field(min_length=1)
    consumed_at: datetime
    receipt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


_SEPARATE_APPROVAL_CAPABILITIES = frozenset({
    "checkpoint.restore", "component.install", "component.execute", "git.push",
    "system.activate", "system.rollback",
})
_SEPARATE_APPROVAL_PREFIXES = (
    "api.", "cloudformation.", "container.", "database.", "dependency.",
    "deployment.", "docker.", "helm.", "infrastructure.", "kubernetes.",
    "mcp.", "service.", "terraform.", "vulnerability.",
)
_SEPARATE_APPROVAL_OPERATIONS = frozenset({
    "activation", "apply", "delete", "deploy", "destructive", "install",
    "publish", "push", "rollback", "scope_expand",
})


def requires_separate_approval(call: CapabilityCall) -> bool:
    """Return true for effects that may not share a multi-call approval envelope."""
    return bool(
        call.capability_id in _SEPARATE_APPROVAL_CAPABILITIES
        or call.capability_id.startswith(_SEPARATE_APPROVAL_PREFIXES)
        or call.operation.casefold() in _SEPARATE_APPROVAL_OPERATIONS
        or call.mode.value != "native"
        or call.privacy_boundary != "local"
        or call.cost_boundary != "local"
    )


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
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS approval_envelopes (
                envelope_id TEXT PRIMARY KEY,
                principal TEXT NOT NULL,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                task_revision INTEGER NOT NULL,
                project_fingerprint TEXT NOT NULL,
                current_project_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                approved_at TEXT,
                consumed_at TEXT,
                receipt_digest TEXT
            )"""
        )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS approval_envelope_calls (
                envelope_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                call_digest TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                target_path TEXT,
                status TEXT NOT NULL,
                reserved_at TEXT,
                consumed_at TEXT,
                before_fingerprint TEXT,
                after_fingerprint TEXT,
                outcome TEXT,
                PRIMARY KEY(envelope_id, ordinal),
                FOREIGN KEY(envelope_id) REFERENCES approval_envelopes(envelope_id)
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

    def propose_envelope(
        self,
        *,
        principal: str,
        project_id: str,
        task_id: str,
        task_revision: int,
        calls: Sequence[CapabilityCall],
        project_fingerprint: str,
        expires_at: datetime | None = None,
    ) -> ApprovalEnvelope:
        planned = tuple(calls)
        if not planned:
            raise ValueError("approval envelope requires at least one call")
        if len(planned) > 32:
            raise ValueError("approval envelope exceeds 32 calls")
        if any(requires_separate_approval(call) for call in planned):
            raise PermissionError("destructive, network, publication, and scope-expanding calls require separate approval")
        created_at = datetime.now(UTC)
        expiry = expires_at or created_at + timedelta(minutes=5)
        call_digests = tuple(self._call_digest(call) for call in planned)
        envelope_id = f"envelope:{canonical_digest(call_digests)[7:23]}:{uuid7()}"
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT INTO approval_envelopes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        envelope_id, principal, project_id, task_id, task_revision,
                        project_fingerprint, project_fingerprint, "pending",
                        created_at.isoformat(), expiry.isoformat(), None, None, None,
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO approval_envelope_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        (
                            envelope_id, ordinal, digest, call.capability_id, call.operation,
                            call.target_path, "pending", None, None, None, None, None,
                        )
                        for ordinal, (call, digest) in enumerate(zip(planned, call_digests, strict=True))
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_envelope(envelope_id)

    def get_envelope(self, envelope_id: str) -> ApprovalEnvelope:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approval_envelopes WHERE envelope_id = ?", (envelope_id,)
            ).fetchone()
            if row is None:
                raise KeyError(envelope_id)
            calls = self._connection.execute(
                "SELECT * FROM approval_envelope_calls WHERE envelope_id = ? ORDER BY ordinal",
                (envelope_id,),
            ).fetchall()
        return self._envelope(row, calls)

    @staticmethod
    def _validate_envelope_binding(
        envelope: ApprovalEnvelope,
        *,
        principal: str,
        project_id: str,
        project_fingerprint: str,
        task_revision: int,
    ) -> None:
        if principal != envelope.principal:
            raise PermissionError("approval envelope principal does not match")
        if project_id != envelope.project_id:
            raise PermissionError("approval envelope project does not match")
        if project_fingerprint != envelope.current_project_fingerprint:
            raise PermissionError("approval envelope project fingerprint does not match")
        if task_revision != envelope.task_revision:
            raise PermissionError("approval envelope task revision does not match")

    def approve_envelope(
        self,
        envelope_id: str,
        *,
        principal: str,
        project_id: str,
        project_fingerprint: str,
        task_revision: int,
        now: datetime | None = None,
    ) -> ApprovalEnvelope:
        approved_at = now or datetime.now(UTC)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                envelope = self.get_envelope(envelope_id)
                if envelope.status != "pending":
                    raise PermissionError(f"approval envelope is {envelope.status}")
                if approved_at >= envelope.expires_at:
                    raise PermissionError("approval envelope is expired")
                self._validate_envelope_binding(
                    envelope, principal=principal, project_id=project_id,
                    project_fingerprint=project_fingerprint, task_revision=task_revision,
                )
                updated = self._connection.execute(
                    "UPDATE approval_envelopes SET status = 'approved', approved_at = ? "
                    "WHERE envelope_id = ? AND status = 'pending'",
                    (approved_at.isoformat(), envelope_id),
                )
                if updated.rowcount != 1:
                    raise PermissionError("approval envelope was already approved")
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_envelope(envelope_id)

    def reserve_envelope_call(
        self,
        envelope_id: str,
        *,
        principal: str,
        project_id: str,
        call: CapabilityCall,
        project_fingerprint: str,
        task_revision: int,
        now: datetime | None = None,
    ) -> ApprovalEnvelopeLease:
        reserved_at = now or datetime.now(UTC)
        call_digest = self._call_digest(call)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                envelope = self.get_envelope(envelope_id)
                if envelope.status == "consumed":
                    raise PermissionError("approval envelope call replay detected")
                if envelope.status != "approved":
                    raise PermissionError(f"approval envelope is {envelope.status}")
                if reserved_at >= envelope.expires_at:
                    raise PermissionError("approval envelope is expired")
                self._validate_envelope_binding(
                    envelope, principal=principal, project_id=project_id,
                    project_fingerprint=project_fingerprint, task_revision=task_revision,
                )
                if any(item.status == "reserved" for item in envelope.calls):
                    raise PermissionError("approval envelope already has a call in progress")
                call_item = next(
                    (item for item in envelope.calls if item.call_digest == call_digest and item.status == "pending"),
                    None,
                )
                if call_item is None:
                    if any(item.call_digest == call_digest for item in envelope.calls):
                        raise PermissionError("approval envelope call replay detected")
                    raise PermissionError("call is outside the approval envelope")
                updated = self._connection.execute(
                    """UPDATE approval_envelope_calls
                       SET status = 'reserved', reserved_at = ?, before_fingerprint = ?
                       WHERE envelope_id = ? AND ordinal = ? AND status = 'pending'""",
                    (reserved_at.isoformat(), project_fingerprint, envelope_id, call_item.ordinal),
                )
                if updated.rowcount != 1:
                    raise PermissionError("approval envelope call was already reserved")
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return ApprovalEnvelopeLease(
            envelope_id=envelope_id, ordinal=call_item.ordinal, principal=principal,
            project_id=project_id, task_id=envelope.task_id, task_revision=task_revision,
            call_digest=call_digest, project_fingerprint=project_fingerprint,
            reserved_at=reserved_at, expires_at=envelope.expires_at,
        )

    def record_envelope_result(
        self,
        lease: ApprovalEnvelopeLease,
        *,
        project_fingerprint: str,
        outcome: EnvelopeOutcome,
        now: datetime | None = None,
    ) -> ApprovalEnvelopeReceipt | None:
        consumed_at = now or datetime.now(UTC)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                envelope = self.get_envelope(lease.envelope_id)
                if envelope.status != "approved":
                    raise PermissionError(f"approval envelope is {envelope.status}")
                if envelope.task_revision != lease.task_revision:
                    raise PermissionError("approval envelope task revision does not match")
                if envelope.current_project_fingerprint != lease.project_fingerprint:
                    raise PermissionError("approval envelope project fingerprint does not match reserved call")
                item = next((value for value in envelope.calls if value.ordinal == lease.ordinal), None)
                if item is None or item.status != "reserved" or item.call_digest != lease.call_digest:
                    raise PermissionError("approval envelope lease is not active")
                updated = self._connection.execute(
                    """UPDATE approval_envelope_calls
                       SET status = 'consumed', consumed_at = ?, after_fingerprint = ?, outcome = ?
                       WHERE envelope_id = ? AND ordinal = ? AND status = 'reserved'""",
                    (consumed_at.isoformat(), project_fingerprint, outcome, lease.envelope_id, lease.ordinal),
                )
                if updated.rowcount != 1:
                    raise PermissionError("approval envelope lease was already consumed")
                remaining = self._connection.execute(
                    "SELECT COUNT(*) FROM approval_envelope_calls WHERE envelope_id = ? AND status != 'consumed'",
                    (lease.envelope_id,),
                ).fetchone()[0]
                receipt_digest = None
                status = "approved"
                if remaining == 0:
                    rows = self._connection.execute(
                        "SELECT * FROM approval_envelope_calls WHERE envelope_id = ? ORDER BY ordinal",
                        (lease.envelope_id,),
                    ).fetchall()
                    evidence = [
                        {
                            "ordinal": int(row["ordinal"]), "call_digest": row["call_digest"],
                            "before_fingerprint": row["before_fingerprint"],
                            "after_fingerprint": row["after_fingerprint"], "outcome": row["outcome"],
                        }
                        for row in rows
                    ]
                    receipt_digest = canonical_digest({
                        "envelope_id": lease.envelope_id, "principal": envelope.principal,
                        "project_id": envelope.project_id, "task_id": envelope.task_id,
                        "task_revision": envelope.task_revision, "calls": evidence,
                    })
                    status = "consumed"
                self._connection.execute(
                    """UPDATE approval_envelopes
                       SET current_project_fingerprint = ?, status = ?, consumed_at = ?, receipt_digest = ?
                       WHERE envelope_id = ?""",
                    (
                        project_fingerprint, status,
                        consumed_at.isoformat() if status == "consumed" else None,
                        receipt_digest, lease.envelope_id,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        if status != "consumed":
            return None
        return self.receipt(lease.envelope_id)

    def receipt(self, envelope_id: str) -> ApprovalEnvelopeReceipt:
        envelope = self.get_envelope(envelope_id)
        if envelope.status != "consumed" or envelope.consumed_at is None or envelope.receipt_digest is None:
            raise PermissionError("approval envelope has no final receipt")
        return ApprovalEnvelopeReceipt(
            envelope_id=envelope.envelope_id, task_id=envelope.task_id,
            task_revision=envelope.task_revision,
            call_digests=tuple(item.call_digest for item in envelope.calls),
            outcomes=tuple(item.outcome for item in envelope.calls if item.outcome is not None),
            initial_project_fingerprint=envelope.project_fingerprint,
            final_project_fingerprint=envelope.current_project_fingerprint,
            consumed_at=envelope.consumed_at, receipt_digest=envelope.receipt_digest,
        )

    def revoke_envelope(self, envelope_id: str) -> ApprovalEnvelope:
        with self._lock, self._connection:
            updated = self._connection.execute(
                "UPDATE approval_envelopes SET status = 'revoked' "
                "WHERE envelope_id = ? AND status IN ('pending', 'approved')",
                (envelope_id,),
            )
        if updated.rowcount != 1:
            envelope = self.get_envelope(envelope_id)
            if envelope.status != "revoked":
                raise PermissionError(f"approval envelope is {envelope.status}")
        return self.get_envelope(envelope_id)

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
            envelopes = self._connection.execute(
                "UPDATE approval_envelopes SET status = 'revoked' "
                "WHERE task_id = ? AND status IN ('pending', 'approved')",
                (task_id,),
            )
        return result.rowcount + envelopes.rowcount

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

    @staticmethod
    def _envelope(row: sqlite3.Row, calls: Sequence[sqlite3.Row]) -> ApprovalEnvelope:
        return ApprovalEnvelope(
            envelope_id=row["envelope_id"], principal=row["principal"],
            project_id=row["project_id"], task_id=row["task_id"],
            task_revision=int(row["task_revision"]),
            project_fingerprint=row["project_fingerprint"],
            current_project_fingerprint=row["current_project_fingerprint"],
            calls=tuple(
                ApprovalEnvelopeCall(
                    ordinal=int(call["ordinal"]), call_digest=call["call_digest"],
                    capability_id=call["capability_id"], operation=call["operation"],
                    target_path=call["target_path"], status=call["status"],
                    reserved_at=None if call["reserved_at"] is None else datetime.fromisoformat(call["reserved_at"]),
                    consumed_at=None if call["consumed_at"] is None else datetime.fromisoformat(call["consumed_at"]),
                    before_fingerprint=call["before_fingerprint"],
                    after_fingerprint=call["after_fingerprint"], outcome=call["outcome"],
                )
                for call in calls
            ),
            status=row["status"], created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            approved_at=None if row["approved_at"] is None else datetime.fromisoformat(row["approved_at"]),
            consumed_at=None if row["consumed_at"] is None else datetime.fromisoformat(row["consumed_at"]),
            receipt_digest=row["receipt_digest"],
        )
