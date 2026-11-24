from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid7

from pydantic import Field

from web_app.core.contracts import (
    EffectIntentDraft,
    EffectState,
    FrozenContract,
    TaskCommand,
    TaskEventDraft,
)
from web_app.core.git_adapter import VerificationReceipt
from web_app.core.store import ConcurrencyConflict, InvalidEffectTransition, TaskStore
from web_app.core.worktree_runtime import WorktreeRuntime, WorktreeSession


class CandidateState(str, Enum):
    proposed = "proposed"
    staged = "staged"
    modified = "modified"
    verification_pending = "verification_pending"
    verified = "verified"
    committed = "committed"
    published = "published"
    health_pending = "health_pending"
    healthy = "healthy"
    activated = "activated"
    rolled_back = "rolled_back"
    rejected = "rejected"
    verification_failed = "verification_failed"
    publication_failed = "publication_failed"
    health_failed = "health_failed"


class InvalidCandidateTransition(RuntimeError):
    pass


class AmbiguousEffect(RuntimeError):
    """An external side effect may have succeeded and must be reconciled before retry."""


class UpdateProfile(FrozenContract):
    profile_id: str = Field(min_length=1, max_length=128)
    repository_root: str = Field(min_length=1, max_length=4096)
    branch: str = Field(min_length=1, max_length=200)
    expected_remote_sha: str | None = None
    mandatory_checks: tuple[str, ...] = Field(min_length=1)
    allowed_repository_roots: tuple[str, ...] = ()
    automatic_mode_enabled: bool = False
    expected_version: str | None = None


class CandidateRecord(FrozenContract):
    candidate_id: str
    task_id: str
    profile_id: str
    prompt: str
    principal_id: str
    credential_id: str
    scopes: tuple[str, ...]
    state: CandidateState
    proposed_at: datetime
    base_sha: str | None = None
    worktree: WorktreeSession | None = None
    verification_receipt: VerificationReceipt | None = None
    commit_sha: str | None = None
    publication_receipt: Mapping[str, Any] | None = None
    health_receipt: Mapping[str, Any] | None = None
    activation_receipt: Mapping[str, Any] | None = None
    rollback_receipt: Mapping[str, Any] | None = None
    quarantine_reason: str | None = None
    automatic_mode_enabled: bool = False


_EVENT_STATES = {
    "candidate.proposed": CandidateState.proposed,
    "candidate.staged": CandidateState.staged,
    "candidate.modified": CandidateState.modified,
    "candidate.verification_requested": CandidateState.verification_pending,
    "candidate.verification_completed": CandidateState.verified,
    "candidate.committed": CandidateState.committed,
    "candidate.published": CandidateState.published,
    "candidate.health_requested": CandidateState.health_pending,
    "candidate.health_completed": CandidateState.healthy,
    "candidate.activated": CandidateState.activated,
    "candidate.rolled_back": CandidateState.rolled_back,
    "candidate.rejected": CandidateState.rejected,
    "candidate.verification_failed": CandidateState.verification_failed,
    "candidate.publication_failed": CandidateState.publication_failed,
    "candidate.health_failed": CandidateState.health_failed,
}


class AutonomousUpdateController:
    """Durable candidate state machine projected exclusively from TaskStore events."""

    command_type = "system.update.candidate"

    def __init__(
        self,
        *,
        store: TaskStore,
        profiles: Mapping[str, UpdateProfile],
        worktrees: WorktreeRuntime,
        verifier: object | None = None,
        publisher: object | None = None,
        launcher: object | None = None,
    ) -> None:
        self._store = store
        self._profiles = dict(profiles)
        self._worktrees = worktrees
        self._verifier = verifier
        self._publisher = publisher
        self._launcher = launcher

    def propose(self, profile_id: str, prompt: str, principal) -> CandidateRecord:
        profile = self._profile(profile_id)
        principal_id = getattr(principal, "user_id", None)
        credential_id = getattr(principal, "credential_id", None)
        scopes = tuple(getattr(principal, "scopes", ()))
        if not principal_id or not credential_id or "system.update" not in scopes:
            raise PermissionError("candidate proposal requires a scoped authenticated principal")
        if not prompt.strip():
            raise ValueError("candidate prompt is required")
        self._assert_profile_scope(profile)
        candidate_id = f"candidate-{uuid7()}"
        task_id = candidate_id
        proposed_at = datetime.now(UTC)
        command = TaskCommand(
            command_id=f"proposal:{candidate_id}",
            task_id=task_id,
            thread_id=f"update:{profile_id}",
            project_id=profile_id,
            command_type=self.command_type,
            payload={
                "candidate_id": candidate_id,
                "profile_id": profile_id,
                "prompt": prompt.strip(),
                "principal_id": principal_id,
                "credential_id": credential_id,
                "scopes": list(scopes),
                "proposed_at": proposed_at.isoformat(),
            },
        )
        self._store.create(command)
        self._store.append(
            task_id,
            TaskEventDraft(
                event_type="candidate.proposed",
                payload={
                    "candidate_id": candidate_id,
                    "profile_id": profile_id,
                    "principal_id": principal_id,
                    "credential_id": credential_id,
                },
                causation_id=command.command_id,
            ),
        )
        return self.get(candidate_id)

    def get(self, candidate_id: str) -> CandidateRecord:
        command = self._store.command(candidate_id)
        if command.command_type != self.command_type:
            raise KeyError(candidate_id)
        payload = command.payload
        record: dict[str, Any] = {
            "candidate_id": candidate_id,
            "task_id": candidate_id,
            "profile_id": payload["profile_id"],
            "prompt": payload["prompt"],
            "principal_id": payload["principal_id"],
            "credential_id": payload["credential_id"],
            "scopes": tuple(payload.get("scopes", ())),
            "state": CandidateState.proposed,
            "proposed_at": datetime.fromisoformat(str(payload["proposed_at"])),
            "automatic_mode_enabled": False,
        }
        for event in self._store.events(candidate_id):
            state = _EVENT_STATES.get(event.event_type)
            if state is not None:
                record["state"] = state
            values = event.payload
            if event.event_type == "candidate.staged":
                record["worktree"] = WorktreeSession.model_validate(values["worktree"])
                record["base_sha"] = values["base_sha"]
            elif event.event_type == "candidate.verification_completed":
                record["verification_receipt"] = VerificationReceipt.model_validate(values["receipt"])
            elif event.event_type == "candidate.verification_invalidated":
                record["state"] = CandidateState.modified
                record["verification_receipt"] = None
            elif event.event_type == "candidate.committed":
                record["commit_sha"] = values["commit_sha"]
            elif event.event_type == "candidate.published":
                record["publication_receipt"] = dict(values["receipt"])
            elif event.event_type == "candidate.health_completed":
                record["health_receipt"] = dict(values["receipt"])
            elif event.event_type == "candidate.activated":
                record["activation_receipt"] = dict(values["receipt"])
            elif event.event_type == "candidate.rolled_back":
                record["rollback_receipt"] = dict(values["receipt"])
            elif event.event_type in {
                "candidate.rejected", "candidate.verification_failed",
                "candidate.publication_failed", "candidate.health_failed",
            }:
                record["quarantine_reason"] = values.get("reason")
        return CandidateRecord.model_validate(record)

    def candidates(self, profile_id: str | None = None) -> tuple[CandidateRecord, ...]:
        records = tuple(
            self.get(task.task_id) for task in self._store.for_command_type(self.command_type)
        )
        if profile_id is None:
            return records
        return tuple(record for record in records if record.profile_id == profile_id)

    def stage(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is not CandidateState.proposed:
            if candidate.worktree is not None:
                return candidate
            raise self._invalid(candidate, "stage")
        profile = self._profile(candidate.profile_id)

        def operation():
            session = self._worktrees.create(profile.repository_root, candidate_id=candidate_id)
            if not session.base_sha:
                raise RuntimeError("self-update candidates require a Git worktree")
            return {"worktree": session.model_dump(mode="json"), "base_sha": session.base_sha}

        return self._effect(candidate, "stage", operation, "candidate.staged")

    def mark_modified(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state not in {CandidateState.staged, CandidateState.verified}:
            if candidate.state is CandidateState.modified:
                return candidate
            raise self._invalid(candidate, "mark modified")
        if candidate.worktree is None or not self._worktrees.has_changes(candidate.worktree):
            raise ValueError("candidate worktree has no changes")
        event_type = (
            "candidate.verification_invalidated"
            if candidate.state is CandidateState.verified else "candidate.modified"
        )
        self._store.append(
            candidate_id,
            TaskEventDraft(event_type=event_type, payload={"reason": "candidate tree changed"}),
        )
        return self.get(candidate_id)

    def verify(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is CandidateState.verified:
            if candidate.worktree and self._worktrees.tree_sha(candidate.worktree) == candidate.verification_receipt.tree_sha:
                return candidate
            candidate = self.mark_modified(candidate_id)
        if candidate.state is CandidateState.staged:
            candidate = self.mark_modified(candidate_id)
        if candidate.state is not CandidateState.modified or candidate.worktree is None:
            raise self._invalid(candidate, "verify")
        if self._verifier is None:
            raise RuntimeError("trusted verification service is not configured")
        profile = self._profile(candidate.profile_id)
        tree_sha = self._worktrees.tree_sha(candidate.worktree)
        self._store.append(
            candidate_id,
            TaskEventDraft(event_type="candidate.verification_requested", payload={"tree_sha": tree_sha}),
        )
        candidate = self.get(candidate_id)

        def operation():
            receipt = self._invoke(
                self._verifier,
                "verify",
                candidate_id=candidate_id,
                base_sha=candidate.base_sha,
                tree_sha=tree_sha,
                checks=profile.mandatory_checks,
                project_root=candidate.worktree.working_root,
            )
            if not isinstance(receipt, VerificationReceipt):
                raise RuntimeError("verification did not return a trusted receipt")
            return {"receipt": receipt.model_dump(mode="json")}

        return self._effect(candidate, "verify", operation, "candidate.verification_completed")

    def commit(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is CandidateState.committed:
            return candidate
        if candidate.state is not CandidateState.verified or candidate.worktree is None or candidate.verification_receipt is None:
            raise self._invalid(candidate, "commit")
        current_tree = self._worktrees.tree_sha(candidate.worktree)
        if current_tree != candidate.verification_receipt.tree_sha:
            self._store.append(
                candidate_id,
                TaskEventDraft(
                    event_type="candidate.verification_invalidated",
                    payload={"reason": "candidate tree changed after verification"},
                ),
            )
            raise InvalidCandidateTransition("candidate tree changed after verification")
        if self._verifier is None or not bool(self._invoke(self._verifier, "validate", candidate.verification_receipt)):
            raise PermissionError("verification receipt is not trusted")

        def operation():
            commit_sha = self._worktrees.commit(candidate.worktree, "Apply verified JSON_CODR self-update")
            return {"commit_sha": commit_sha, "tree_sha": current_tree}

        return self._effect(candidate, "commit", operation, "candidate.committed")

    def publish(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is CandidateState.published:
            return candidate
        if candidate.state is not CandidateState.committed or candidate.worktree is None or not candidate.commit_sha:
            raise self._invalid(candidate, "publish")
        if self._publisher is None:
            raise RuntimeError("verified publisher is not configured")
        profile = self._profile(candidate.profile_id)

        def operation():
            receipt = self._invoke(
                self._publisher, "publish_verified",
                candidate.worktree.working_root, profile.branch,
                candidate.commit_sha, profile.expected_remote_sha,
            )
            return {"receipt": self._json_receipt(receipt)}

        return self._effect(candidate, "publish", operation, "candidate.published")

    def health_check(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is CandidateState.healthy:
            return candidate
        if candidate.state is not CandidateState.published:
            raise self._invalid(candidate, "health check")
        if self._launcher is None:
            raise RuntimeError("candidate launcher is not configured")
        profile = self._profile(candidate.profile_id)
        self._store.append(candidate_id, TaskEventDraft(event_type="candidate.health_requested"))
        candidate = self.get(candidate_id)

        def operation():
            receipt = self._invoke(self._launcher, "launch_candidate", candidate, profile)
            values = self._json_receipt(receipt)
            if values.get("healthy") is not True:
                raise RuntimeError("candidate health checks failed")
            return {"receipt": values}

        return self._effect(candidate, "health", operation, "candidate.health_completed")

    def activate(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is CandidateState.activated:
            return candidate
        if candidate.state is not CandidateState.healthy or candidate.health_receipt is None:
            raise self._invalid(candidate, "activate")
        if "system.activate" not in candidate.scopes:
            raise PermissionError("candidate principal is not scoped for activation")

        def operation():
            receipt = self._invoke(self._launcher, "activate", candidate.health_receipt)
            return {"receipt": self._json_receipt(receipt)}

        return self._effect(candidate, "activate", operation, "candidate.activated")

    def rollback(self, candidate_id: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        if candidate.state is CandidateState.rolled_back:
            return candidate
        if candidate.state is not CandidateState.activated or candidate.activation_receipt is None:
            raise self._invalid(candidate, "rollback")
        if "system.rollback" not in candidate.scopes:
            raise PermissionError("candidate principal is not scoped for rollback")
        activation_id = candidate.activation_receipt.get("activation_id")
        if not isinstance(activation_id, str):
            raise RuntimeError("activation receipt is missing its identity")

        def operation():
            receipt = self._invoke(self._launcher, "rollback", activation_id)
            return {"receipt": self._json_receipt(receipt)}

        return self._effect(candidate, "rollback", operation, "candidate.rolled_back")

    def reconcile(self, candidate_id: str, transition: str) -> CandidateRecord:
        candidate = self.get(candidate_id)
        effect_id = self._effect_id(candidate_id, transition)
        effect = self._store.effect(candidate_id, effect_id)
        if effect.state is not EffectState.unknown_requires_reconciliation:
            raise InvalidCandidateTransition("only ambiguous effects can be reconciled")
        if transition != "publish" or self._publisher is None or not candidate.commit_sha:
            raise InvalidCandidateTransition(f"no reconciler is configured for {transition}")
        profile = self._profile(candidate.profile_id)
        receipt = self._invoke(
            self._publisher, "reconcile_publication", profile.branch, candidate.commit_sha
        )
        values = self._json_receipt(receipt)
        if values.get("status") not in {"published", "already_published"}:
            self._store.reconcile_effect(candidate_id, effect_id, "not_applied")
            self._store.append(
                candidate_id,
                TaskEventDraft(
                    event_type="candidate.publication_failed",
                    payload={"reason": "publication was not applied"},
                ),
            )
            return self.get(candidate_id)
        self._store.complete_effect_with_event(
            candidate_id,
            effect_id,
            TaskEventDraft(event_type="candidate.published", payload={"receipt": values}),
        )
        return self.get(candidate_id)

    def _effect(self, candidate: CandidateRecord, transition: str, operation, success_event: str) -> CandidateRecord:
        effect_id = self._effect_id(candidate.candidate_id, transition)
        reservation = self._store.append_with_effect(
            candidate.task_id,
            TaskEventDraft(event_type=f"candidate.{transition}.effect_requested"),
            EffectIntentDraft(
                effect_id=effect_id,
                capability_id=f"system.update.{transition}",
                operation=transition,
                payload={"candidate_id": candidate.candidate_id, "transition": transition},
                principal=candidate.principal_id,
                project_root=self._profile(candidate.profile_id).repository_root,
                effect_class="self_update",
                approval_required=False,
                retry_classification="reconcile_before_retry",
                reconciler_id=f"self_update.{transition}",
                correlation_id=candidate.candidate_id,
                causation_id=effect_id,
            ),
        )
        if not reservation.created:
            if reservation.effect.state is EffectState.succeeded:
                return self.get(candidate.candidate_id)
            if reservation.effect.state is EffectState.unknown_requires_reconciliation:
                raise InvalidCandidateTransition(
                    f"{transition} has an ambiguous result and must be reconciled"
                )
            if reservation.effect.state is not EffectState.pending:
                raise InvalidCandidateTransition(f"{transition} is already in progress or failed")
        try:
            self._store.transition_effect(
                candidate.task_id, effect_id, EffectState.leased,
                expected_state=EffectState.pending, lease_owner=f"controller-{id(self)}",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            self._store.transition_effect(
                candidate.task_id, effect_id, EffectState.running,
                expected_state=EffectState.leased,
            )
        except ConcurrencyConflict as error:
            raise InvalidCandidateTransition(f"{transition} is already owned by another writer") from error
        try:
            receipt = operation()
        except AmbiguousEffect:
            self._store.transition_effect(
                candidate.task_id, effect_id, EffectState.unknown_requires_reconciliation,
                expected_state=EffectState.running,
            )
            self._store.append(
                candidate.task_id,
                TaskEventDraft(
                    event_type="candidate.effect_ambiguous",
                    payload={"transition": transition}, causation_id=effect_id,
                ),
            )
            raise
        except Exception as error:
            failure_event = {
                "verify": "candidate.verification_failed",
                "publish": "candidate.publication_failed",
                "health": "candidate.health_failed",
            }.get(transition, f"candidate.{transition}.failed")
            self._store.fail_effect_with_event(
                candidate.task_id,
                effect_id,
                TaskEventDraft(
                    event_type=failure_event,
                    payload={"reason": str(error)[:500], "error_type": type(error).__name__},
                ),
            )
            raise
        self._store.complete_effect_with_event(
            candidate.task_id,
            effect_id,
            TaskEventDraft(event_type=success_event, payload=receipt),
        )
        return self.get(candidate.candidate_id)

    def _profile(self, profile_id: str) -> UpdateProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as error:
            raise KeyError(f"unknown update profile: {profile_id}") from error

    @staticmethod
    def _effect_id(candidate_id: str, transition: str) -> str:
        return f"{candidate_id}:{transition}"

    @staticmethod
    def _invalid(candidate: CandidateRecord, transition: str) -> InvalidCandidateTransition:
        return InvalidCandidateTransition(
            f"cannot {transition} candidate {candidate.candidate_id} from {candidate.state.value}"
        )

    @staticmethod
    def _json_receipt(receipt: object) -> dict[str, Any]:
        if hasattr(receipt, "model_dump"):
            return dict(receipt.model_dump(mode="json"))
        if isinstance(receipt, Mapping):
            return dict(receipt)
        raise TypeError("external effect did not return a typed receipt")

    @staticmethod
    def _invoke(target: object, method: str, *args, **kwargs):
        result = getattr(target, method)(*args, **kwargs)
        if inspect.isawaitable(result):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(result)
            raise RuntimeError("async update effects require an async controller boundary")
        return result

    @staticmethod
    def _assert_profile_scope(profile: UpdateProfile) -> None:
        repository = Path(profile.repository_root).resolve(strict=True)
        allowed = tuple(Path(root).resolve(strict=True) for root in profile.allowed_repository_roots)
        if not allowed or not any(repository == root or repository.is_relative_to(root) for root in allowed):
            raise PermissionError(
                f"repository {repository} is outside the update profile's scoped authority"
            )
