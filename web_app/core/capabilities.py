from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from web_app.core.contracts import CapabilityManifest, CapabilityResult, ExecutionMode, RuntimeIdentity


class CapabilityAdapter(Protocol):
    def probe(self, context: RuntimeIdentity) -> bool: ...


AdapterFactory = Callable[[], CapabilityAdapter]


class CapabilityRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[CapabilityManifest, AdapterFactory]] = {}
        self._readiness: dict[tuple[str, RuntimeIdentity], bool] = {}

    def register(self, manifest: CapabilityManifest, adapter_factory: AdapterFactory) -> None:
        if manifest.implementation_id in self._entries:
            raise ValueError(f"duplicate implementation identity: {manifest.implementation_id}")
        self._entries[manifest.implementation_id] = (manifest, adapter_factory)

    def resolve(self, request: Mapping[str, object], context: RuntimeIdentity) -> tuple[CapabilityResult, ...]:
        capability_id = self._required_request_value(request, "capability_id")
        model_id = self._required_request_value(request, "model_id")
        mode = self._request_mode(request)
        if model_id not in context.model_ids:
            return ()

        return tuple(
            CapabilityResult(
                capability_id=manifest.capability_id,
                implementation_id=manifest.implementation_id,
                runnable=True,
            )
            for manifest, _ in self._matching_entries(capability_id, context)
            if self._supports_request(manifest, model_id, mode)
            and self._readiness.get((manifest.implementation_id, context), False)
        )

    def probe(self, capability_id: str, context: RuntimeIdentity) -> tuple[CapabilityResult, ...]:
        entries = self._matching_entries(capability_id, context)
        if not entries:
            raise ValueError(f"unknown or unavailable capability: {capability_id}")

        results = []
        for manifest, adapter_factory in entries:
            try:
                runnable = bool(adapter_factory().probe(context))
            except Exception:
                runnable = False
            self._readiness[(manifest.implementation_id, context)] = runnable
            results.append(
                CapabilityResult(
                    capability_id=manifest.capability_id,
                    implementation_id=manifest.implementation_id,
                    runnable=runnable,
                    reason=None if runnable else "functional probe failed",
                )
            )
        return tuple(results)

    def describe(self) -> tuple[CapabilityManifest, ...]:
        return tuple(
            manifest
            for manifest, _ in sorted(
                self._entries.values(),
                key=lambda entry: (entry[0].capability_id, entry[0].implementation_id),
            )
        )

    def _matching_entries(
        self, capability_id: str, context: RuntimeIdentity
    ) -> tuple[tuple[CapabilityManifest, AdapterFactory], ...]:
        return tuple(
            entry
            for entry in sorted(
                self._entries.values(),
                key=lambda entry: entry[0].implementation_id,
            )
            if entry[0].capability_id == capability_id and self._supports_context(entry[0], context)
        )

    @staticmethod
    def _supports_context(manifest: CapabilityManifest, context: RuntimeIdentity) -> bool:
        return (
            (not manifest.platforms or context.platform in manifest.platforms)
            and set(manifest.runtime_requirements).issubset(context.runtime_ids)
            and set(manifest.required_permissions).issubset(context.granted_permissions)
            and set(manifest.required_packages).issubset(context.installed_packages)
        )

    @staticmethod
    def _supports_request(manifest: CapabilityManifest, model_id: str, mode: ExecutionMode) -> bool:
        if mode not in manifest.modes:
            return False
        models = manifest.native_models if mode is ExecutionMode.native else manifest.brokered_models
        return not models or model_id in models

    @staticmethod
    def _required_request_value(request: Mapping[str, object], field: str) -> str:
        value = request.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"request requires a non-empty {field}")
        return value

    @staticmethod
    def _request_mode(request: Mapping[str, object]) -> ExecutionMode:
        value = request.get("mode")
        try:
            return ExecutionMode(value)
        except (TypeError, ValueError) as error:
            raise ValueError("request requires a known execution mode") from error
