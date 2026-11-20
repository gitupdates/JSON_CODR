from __future__ import annotations

from pathlib import Path

from web_app.core.provider_compatibility import (
    CompatibilityLayer,
    ProviderActivation,
    ProviderEvidence,
    ProviderUpdateRequest,
)


class ExampleProviderAdapter:
    provider_id = "example"

    def __init__(self, data_root: Path) -> None:
        self.root = data_root.resolve() / "providers" / self.provider_id

    async def update(self, request: ProviderUpdateRequest) -> ProviderActivation:
        release = self._resolve_exact_release(request.version)
        candidate = self._acquire_isolated(release)
        evidence = await self._probe_twice(candidate)
        generation = self._activate_compare_and_swap(candidate, request.approve_major)
        return ProviderActivation(
            provider_id=self.provider_id,
            version=request.version,
            generation=generation,
            evidence=evidence,
        )

    def _resolve_exact_release(self, version: str):
        raise NotImplementedError("resolve version, source URL, and publisher digest without executing package code")

    def _acquire_isolated(self, release):
        raise NotImplementedError("stage, verify lock/digest and path containment, then promote immutably")

    async def _probe_twice(self, candidate) -> ProviderEvidence:
        raise NotImplementedError("run a harmless real capability across a clean restart and hash the evidence")

    def _activate_compare_and_swap(self, candidate, approved: bool) -> int:
        raise NotImplementedError("activate by generation and retain the last-known-good version")


async def update_example(version: str, data_root: Path, *, approved: bool = False) -> ProviderActivation:
    layer = CompatibilityLayer([ExampleProviderAdapter(data_root)])
    return await layer.update(ProviderUpdateRequest(
        provider_id="example",
        version=version,
        approve_major=approved,
    ))
