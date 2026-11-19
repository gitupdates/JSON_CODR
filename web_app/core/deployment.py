from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid7

from web_app.core.external_effects import ExternalEffectReceipt, ExternalTarget, PreviewEvidence, RollbackClass


class DeploymentAdapter(Protocol):
    adapter_id: str
    version: str
    rollback_class: RollbackClass
    def remote_fingerprint(self, target: ExternalTarget) -> str: ...
    def preview(self, target: ExternalTarget, plan: Mapping[str, object]) -> tuple[str, str]: ...
    def apply(self, target: ExternalTarget, plan: Mapping[str, object]) -> str: ...
    def health(self, target: ExternalTarget) -> bool: ...
    def rollback(self, target: ExternalTarget, receipt: ExternalEffectReceipt) -> str: ...


class DeploymentRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, DeploymentAdapter] = {}
        self._enabled: set[str] = set()

    def register(self, adapter: DeploymentAdapter, *, enabled: bool = False) -> None:
        self._adapters[adapter.adapter_id] = adapter
        if enabled:
            self._enabled.add(adapter.adapter_id)

    def enable(self, adapter_id: str) -> None:
        if adapter_id not in self._adapters:
            raise KeyError(adapter_id)
        self._enabled.add(adapter_id)

    def resolve(self, adapter_id: str) -> DeploymentAdapter:
        if adapter_id not in self._enabled:
            raise PermissionError("deployment adapter is disabled")
        return self._adapters[adapter_id]


class DeploymentService:
    def __init__(self, registry: DeploymentRegistry) -> None:
        self.registry = registry
        self._plans: dict[str, Mapping[str, object]] = {}
        self._receipts: dict[str, ExternalEffectReceipt] = {}

    def preview(self, adapter_id: str, target: ExternalTarget, plan: Mapping[str, object]) -> PreviewEvidence:
        adapter = self.registry.resolve(adapter_id)
        plan_digest, summary = adapter.preview(target, plan)
        preview = PreviewEvidence(
            preview_id=f"preview:{uuid7()}", adapter_id=adapter.adapter_id,
            adapter_version=adapter.version, target=target, plan_digest=plan_digest,
            remote_fingerprint=adapter.remote_fingerprint(target),
            rollback_class=adapter.rollback_class, summary=summary,
            created_at=datetime.now(UTC), expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        self._plans[preview.preview_id] = dict(plan)
        return preview

    def apply(self, preview: PreviewEvidence, *, approved_plan_digest: str, strong_confirmation: bool = False) -> ExternalEffectReceipt:
        adapter = self.registry.resolve(preview.adapter_id)
        if datetime.now(UTC) >= preview.expires_at:
            raise PermissionError("deployment preview expired")
        if approved_plan_digest != preview.plan_digest:
            raise PermissionError("approved deployment plan digest does not match")
        current = adapter.remote_fingerprint(preview.target)
        if current != preview.remote_fingerprint:
            raise PermissionError("remote target drifted after preview")
        if (preview.target.environment.casefold() == "production" or preview.rollback_class is RollbackClass.unavailable) and not strong_confirmation:
            raise PermissionError("production or non-rollback deployment requires stronger confirmation")
        after = adapter.apply(preview.target, self._plans[preview.preview_id])
        if not adapter.health(preview.target):
            raise RuntimeError("deployment health verification failed")
        receipt = ExternalEffectReceipt(
            effect_id=f"effect:{uuid7()}", preview_id=preview.preview_id,
            target_digest=preview.target.target_digest, plan_digest=preview.plan_digest,
            remote_fingerprint_before=current, remote_fingerprint_after=after,
            status="healthy", observed_at=datetime.now(UTC),
        )
        self._receipts[receipt.effect_id] = receipt
        return receipt

    def rollback(self, adapter_id: str, target: ExternalTarget, effect_id: str, *, approved: bool) -> ExternalEffectReceipt:
        if not approved:
            raise PermissionError("rollback requires separate approval")
        adapter = self.registry.resolve(adapter_id)
        prior = self._receipts[effect_id]
        if prior.target_digest != target.target_digest:
            raise PermissionError("rollback target does not match effect target")
        after = adapter.rollback(target, prior)
        return prior.model_copy(update={
            "effect_id": f"rollback:{uuid7()}", "remote_fingerprint_before": prior.remote_fingerprint_after,
            "remote_fingerprint_after": after, "status": "rolled_back", "observed_at": datetime.now(UTC),
        })
