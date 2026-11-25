from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
from web_app.core.auth import load_or_create_protected_key
from web_app.core.canonical import canonical_json
from web_app.core.contracts import FrozenContract, TaskId
from web_app.models import BrokerActionRequest


class WorktreeRecord(FrozenContract):
    task_id: TaskId
    repository_root: str
    worktree_root: str
    branch: str
    base_commit: str


class MergeEvidence(FrozenContract):
    task_id: TaskId
    branch: str
    commit: str
    output: str


class VerificationReceipt(FrozenContract):
    candidate_id: str
    base_sha: str
    tree_sha: str
    profile_digest: str
    checks: tuple[str, ...]
    verified_at: datetime
    verifier_credential_id: str
    signature: str


class GitVerificationService:
    """Issues server-trusted final-tree receipts from activated verification profiles."""

    def __init__(
        self,
        command_runtime,
        profiles,
        verifier_identity,
        *,
        signing_key: bytes | None = None,
        signing_key_path: str | Path | None = None,
    ) -> None:
        self._runtime = command_runtime
        self._profiles = profiles
        self._verifier_identity = verifier_identity
        if signing_key is not None and signing_key_path is not None:
            raise ValueError("provide either a verification signing key or key path")
        if signing_key is None:
            if signing_key_path is None:
                raise ValueError("verification receipt signing key is required")
            signing_key = load_or_create_protected_key(Path(signing_key_path))
        if len(signing_key) < 32:
            raise ValueError("verification receipt signing key must contain at least 32 bytes")
        self._signing_key = bytes(signing_key)

    @staticmethod
    def _material(receipt: VerificationReceipt) -> dict:
        return receipt.model_dump(mode="json", exclude={"signature"})

    def _signature(self, receipt: VerificationReceipt) -> str:
        return "hmac-sha256:" + hmac.new(
            self._signing_key,
            canonical_json(self._material(receipt)),
            hashlib.sha256,
        ).hexdigest()

    async def verify(
        self,
        *,
        candidate_id: str,
        base_sha: str,
        tree_sha: str,
        checks: tuple[str, ...],
        project_root: str | Path,
    ) -> VerificationReceipt:
        if not checks:
            raise ValueError("final verification requires at least one profile")
        profile_digest = self._profiles.profile_digest()
        principal = self._verifier_identity.status()
        credential_id = getattr(principal, "credential_id", None)
        if not credential_id:
            raise PermissionError("verifier identity requires a credential")
        for profile_id in checks:
            result = await self._runtime.run_profile(
                profile_id=profile_id, values={}, project_root=project_root,
            )
            if result.timed_out or result.exit_code:
                detail = result.stderr.strip() or result.stdout.strip() or profile_id
                raise RuntimeError(f"Verification failed: {detail}")
        if self._profiles.profile_digest() != profile_digest:
            raise RuntimeError("verification profile digest changed during verification")
        unsigned = VerificationReceipt(
            candidate_id=candidate_id,
            base_sha=base_sha,
            tree_sha=tree_sha,
            profile_digest=profile_digest,
            checks=checks,
            verified_at=datetime.now(timezone.utc),
            verifier_credential_id=credential_id,
            signature="hmac-sha256:" + "0" * 64,
        )
        return unsigned.model_copy(update={"signature": self._signature(unsigned)})

    def validate(self, receipt: VerificationReceipt) -> bool:
        if not hmac.compare_digest(receipt.signature, self._signature(receipt)):
            return False
        if self._profiles.profile_digest() != receipt.profile_digest:
            return False
        principal = self._verifier_identity.status()
        return getattr(principal, "credential_id", None) == receipt.verifier_credential_id


class GitAdapter:
    def __init__(self, broker) -> None:
        self._broker = broker

    def create_worktree(
        self, repository_root: str | Path, worktree_root: str | Path, branch: str, task_id: str
    ) -> WorktreeRecord:
        values = self._broker.create_worktree(repository_root, worktree_root, branch)
        return WorktreeRecord(
            task_id=task_id,
            **values,
        )

    def merge_worktree(self, repository_root: str | Path, record: WorktreeRecord) -> MergeEvidence:
        values = self._broker.merge_worktree_branch(repository_root, record.branch)
        return MergeEvidence(task_id=record.task_id, **values)


class GitExecutionAdapter:
    def __init__(self, broker, authorized, verification_service: GitVerificationService | None = None) -> None:
        self._broker = broker
        self._authorized = authorized
        self._verification_service = verification_service

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        request_value = call.arguments.get("request")
        if not isinstance(request_value, Mapping):
            raise ValueError("git execution requires a broker request")
        request = BrokerActionRequest.model_validate(dict(request_value))
        if call.capability_id == "git.read" and any(
            action.kind not in {"status", "read"} for action in request.actions
        ):
            raise PermissionError("git.read accepts read-only broker actions only")
        model = call.arguments.get("model")
        grant_id = call.arguments.get("grant_id")
        if not isinstance(model, str) or not isinstance(grant_id, str):
            raise ValueError("git execution requires model and grant identity")

        def authorized() -> bool:
            return bool(self._authorized(grant_id, request.project_root))

        if not authorized():
            raise PermissionError("broker authorization does not cover this project")

        def verify(action, *, candidate_id: str, base_sha: str, tree_sha: str):
            if self._verification_service is None:
                raise RuntimeError("trusted verification service is not configured")
            return asyncio.run(self._verification_service.verify(
                candidate_id=candidate_id,
                base_sha=base_sha,
                tree_sha=tree_sha,
                checks=tuple(action.checks),
                project_root=request.project_root,
            ))

        receipt_validator = None if self._verification_service is None else self._verification_service.validate
        result = await asyncio.to_thread(
            self._broker.execute, request, model, grant_id, authorized,
            verification_runner=verify,
            receipt_validator=receipt_validator,
        )
        yield AdapterEvent(event_type="git.completed", payload={"result": asdict(result)})
