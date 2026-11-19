from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from web_app.core.provider_compatibility import (
    ProviderActivation,
    ProviderEvidence,
    ProviderUpdateRequest,
)


class ReaCompatibilityAdapter:
    provider_id = "rea"

    def __init__(self, data_root: Path, updater: Callable[[str, Path, bool], Awaitable[dict]]) -> None:
        self.data_root = data_root
        self.updater = updater

    async def update(self, request: ProviderUpdateRequest) -> ProviderActivation:
        result = await self.updater(request.version, self.data_root, request.approve_major)
        activation = result.get("activation", {})
        evidence = result.get("evidence", {})
        digest = str(evidence.get("catalog_digest", ""))
        if not digest:
            raise RuntimeError("REA updater returned no catalog verification digest")
        return ProviderActivation(
            provider_id=self.provider_id,
            version=str(activation.get("version", "")),
            generation=int(activation.get("generation", 0)),
            evidence=ProviderEvidence(
                provider_id=self.provider_id,
                version=str(evidence.get("version", "")),
                probe=str(evidence.get("harmless_tool", "")),
                evidence_digest=digest,
                details=dict(evidence),
            ),
        )
