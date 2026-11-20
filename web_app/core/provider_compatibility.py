from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class ProviderUpdateRequest:
    provider_id: str
    version: str
    approve_major: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id or not self.version:
            raise ValueError("provider identity and exact version are required")


@dataclass(frozen=True)
class ProviderEvidence:
    provider_id: str
    version: str
    probe: str
    evidence_digest: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderActivation:
    provider_id: str
    version: str
    generation: int
    evidence: ProviderEvidence | None


class ProviderCompatibilityAdapter(Protocol):
    provider_id: str

    async def update(self, request: ProviderUpdateRequest) -> ProviderActivation: ...


class CompatibilityLayer:
    def __init__(self, adapters: Sequence[ProviderCompatibilityAdapter]) -> None:
        self._adapters: dict[str, ProviderCompatibilityAdapter] = {}
        for adapter in adapters:
            if adapter.provider_id in self._adapters:
                raise ValueError(f"duplicate provider adapter: {adapter.provider_id}")
            self._adapters[adapter.provider_id] = adapter

    async def update(self, request: ProviderUpdateRequest) -> ProviderActivation:
        adapter = self._adapters.get(request.provider_id)
        if adapter is None:
            raise LookupError(f"provider adapter is not registered: {request.provider_id}")
        activation = await adapter.update(request)
        if activation.provider_id != request.provider_id or activation.version != request.version:
            raise RuntimeError("provider adapter substituted the requested identity")
        evidence = activation.evidence
        if evidence is None:
            raise RuntimeError("provider activation has no verification evidence")
        if evidence.provider_id != request.provider_id or evidence.version != request.version:
            raise RuntimeError("provider verification evidence has the wrong identity")
        if not evidence.probe or not evidence.evidence_digest.startswith("sha256:"):
            raise RuntimeError("provider verification evidence is incomplete")
        return activation
