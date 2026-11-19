from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import FrozenContract


class AdapterRoute(FrozenContract):
    kind: Literal["native", "compatibility", "unavailable"]
    requested_capability_id: str
    capability_id: str | None
    reason: str


class AdapterFallbackRouter:
    @staticmethod
    def resolve(
        call: CapabilityCall,
        native_capabilities: Collection[str],
        compatibility_capabilities: Collection[str],
    ) -> AdapterRoute:
        if call.capability_id in native_capabilities:
            return AdapterRoute(
                kind="native",
                requested_capability_id=call.capability_id,
                capability_id=call.capability_id,
                reason="verified native capability",
            )
        if call.capability_id in compatibility_capabilities:
            return AdapterRoute(
                kind="compatibility",
                requested_capability_id=call.capability_id,
                capability_id=call.capability_id,
                reason="explicit compatibility adapter",
            )
        return AdapterRoute(
            kind="unavailable",
            requested_capability_id=call.capability_id,
            capability_id=None,
            reason="no verified native or compatibility capability",
        )
