from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import Field, computed_field

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import Digest, FrozenContract


class RollbackClass(str, Enum):
    automatic = "automatic"
    provider = "provider"
    manual = "manual"
    unavailable = "unavailable"


class ExternalTarget(FrozenContract):
    provider: str
    account: str
    subscription: str | None = None
    region: str | None = None
    cluster: str | None = None
    namespace: str | None = None
    service: str
    environment: str
    credential_ref: str = Field(pattern=r"^credential:[A-Za-z0-9._:-]+$")

    @computed_field
    @property
    def target_digest(self) -> Digest:
        return canonical_digest(self.model_dump(mode="json", exclude={"target_digest"}))


class PreviewEvidence(FrozenContract):
    preview_id: str
    adapter_id: str
    adapter_version: str
    target: ExternalTarget
    plan_digest: Digest
    remote_fingerprint: Digest
    rollback_class: RollbackClass
    summary: str
    created_at: datetime
    expires_at: datetime


class ExternalEffectReceipt(FrozenContract):
    effect_id: str
    preview_id: str
    target_digest: Digest
    plan_digest: Digest
    remote_fingerprint_before: Digest
    remote_fingerprint_after: Digest
    status: str
    observed_at: datetime
