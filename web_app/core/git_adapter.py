from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
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


class GitVerificationService:
    """Issues server-trusted final-tree receipts from activated verification profiles."""

    def __init__(self, command_runtime, profiles, verifier_identity) -> None:
        self._runtime = command_runtime
        self._profiles = profiles
        self._verifier_identity = verifier_identity
        self._issued: dict[str, VerificationReceipt] = {}

    @staticmethod
    def _key(receipt: VerificationReceipt) -> str:
        return receipt.model_dump_json()

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
        receipt = VerificationReceipt(
            candidate_id=candidate_id,
            base_sha=base_sha,
            tree_sha=tree_sha,
            profile_digest=profile_digest,
            checks=checks,
            verified_at=datetime.now(timezone.utc),
            verifier_credential_id=credential_id,
        )
        self._issued[self._key(receipt)] = receipt
        return receipt

    def validate(self, receipt: VerificationReceipt) -> bool:
        if self._issued.get(self._key(receipt)) != receipt:
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
