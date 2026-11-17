from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field

from web_app.core.contracts import ExecutionMode, FrozenContract


class RouteConsentRequired(PermissionError):
    pass


class ExecutionCandidate(FrozenContract):
    route_id: str
    model_id: str
    mode: ExecutionMode
    compatible: bool
    verified: bool
    privacy_boundary: str
    cost_boundary: str
    priority: int = Field(ge=0)


class ExecutionRoute(FrozenContract):
    route_id: str
    requested_model_id: str | None
    effective_model_id: str
    mode: ExecutionMode
    privacy_boundary: str
    cost_boundary: str
    fallback_used: bool


class ExecutionRouter:
    def __init__(self, candidates: Sequence[ExecutionCandidate]) -> None:
        self._candidates = tuple(candidates)

    def resolve(self, requirements: Mapping, preferences: Mapping) -> ExecutionRoute:
        requested = requirements.get("model_id")
        eligible = [candidate for candidate in self._candidates if candidate.compatible and candidate.verified]
        exact = next((candidate for candidate in eligible if candidate.model_id == requested), None)
        candidate = exact or min(
            (
                item for item in eligible
                if item.privacy_boundary == preferences.get("privacy_boundary", "local")
                and item.cost_boundary == preferences.get("cost_boundary", "local")
            ),
            key=lambda item: item.priority,
            default=None,
        )
        if candidate is None:
            raise LookupError("no verified compatible execution route")
        if (
            candidate.privacy_boundary != preferences.get("privacy_boundary", "local")
            or candidate.cost_boundary != preferences.get("cost_boundary", "local")
        ):
            raise RouteConsentRequired("route crosses the approved privacy or cost boundary")
        return ExecutionRoute(
            route_id=candidate.route_id,
            requested_model_id=requested,
            effective_model_id=candidate.model_id,
            mode=candidate.mode,
            privacy_boundary=candidate.privacy_boundary,
            cost_boundary=candidate.cost_boundary,
            fallback_used=requested is not None and candidate.model_id != requested,
        )
