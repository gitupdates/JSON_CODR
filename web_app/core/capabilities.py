from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from web_app.core.contracts import CapabilityManifest, CapabilityResult, CapabilityStatus, ExecutionMode, ModelScope, ProbeObservation, RuntimeIdentity


class CapabilityAdapter(Protocol):
    def probe(self, request: Mapping[str, object], context: RuntimeIdentity) -> object: ...


AdapterFactory = Callable[[], CapabilityAdapter]
ProbeVerifier = Callable[[ProbeObservation], bool]
RegistryEntry = tuple[CapabilityManifest, AdapterFactory, ProbeVerifier]
ReadinessKey = tuple[
    str,
    str,
    str | None,
    str | None,
    str | None,
    ExecutionMode,
    str,
    tuple[str, ...],
    tuple[str, ...],
    str,
    str,
    str,
]


class CapabilityRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}
        self._readiness: dict[ReadinessKey, CapabilityResult] = {}

    def register(
        self, manifest: CapabilityManifest, adapter_factory: AdapterFactory, probe_verifier: ProbeVerifier
    ) -> None:
        if manifest.implementation_id in self._entries:
            raise ValueError(f"duplicate implementation identity: {manifest.implementation_id}")
        self._entries[manifest.implementation_id] = (manifest, adapter_factory, probe_verifier)

    def resolve(self, request: Mapping[str, object], context: RuntimeIdentity) -> tuple[CapabilityResult, ...]:
        capability_id = self._required_request_value(request, "capability_id")
        requested_model_id, effective_model_id = self._request_models(request)
        mode = self._request_mode(request)
        if requested_model_id is not None and requested_model_id not in context.model_ids:
            return ()

        results = []
        for manifest, _, _ in self._entries_for_capability(capability_id):
            if not self._supports_request(manifest, effective_model_id, mode):
                continue
            result = self._readiness.get(
                self._readiness_key(manifest, requested_model_id, effective_model_id, mode, context)
            )
            if result is not None and result.runnable:
                results.append(result)
        return tuple(results)

    def probe(self, request: Mapping[str, object], context: RuntimeIdentity) -> tuple[CapabilityResult, ...]:
        capability_id = self._required_request_value(request, "capability_id")
        requested_model_id, effective_model_id = self._request_models(request)
        mode = self._request_mode(request)
        entries = self._entries_for_capability(capability_id)
        if not entries:
            raise ValueError(f"unknown capability: {capability_id}")

        results = []
        for manifest, adapter_factory, probe_verifier in entries:
            status, evidence = self._preflight_status(manifest, effective_model_id, mode, context)
            runnable = False
            if status is None:
                try:
                    evidence = ProbeObservation.model_validate(
                        adapter_factory().probe(request, context), from_attributes=True
                    )
                    runnable = bool(probe_verifier(evidence))
                    status = CapabilityStatus.ready if runnable else CapabilityStatus.verification_failed
                except Exception:
                    evidence = self._failure_observation("probe.exception", "functional probe failed")
                    status = CapabilityStatus.verification_failed
            result = CapabilityResult(
                capability_id=manifest.capability_id,
                implementation_id=manifest.implementation_id,
                status=status,
                runnable=runnable,
                requested_model_id=requested_model_id,
                effective_model_id=effective_model_id,
                mode=mode,
                manifest_digest=manifest.manifest_digest,
                model_digest=context.model_digests.get(effective_model_id) if effective_model_id else None,
                runtime_fingerprint=context.runtime_fingerprint,
                hardware_profile_id=context.hardware_profile_id,
                hardware_fingerprint=context.hardware_fingerprint,
                evidence=evidence,
                required_permissions=manifest.required_permissions,
                reason=None if runnable else evidence.safe_message,
            )
            self._readiness[
                self._readiness_key(manifest, requested_model_id, effective_model_id, mode, context)
            ] = result
            results.append(result)
        return tuple(results)

    def describe(self) -> tuple[CapabilityManifest, ...]:
        return tuple(
            manifest
            for manifest, _, _ in sorted(
                self._entries.values(),
                key=lambda entry: (entry[0].capability_id, entry[0].implementation_id),
            )
        )

    def has_capability(self, capability_id: str) -> bool:
        return any(manifest.capability_id == capability_id for manifest, _, _ in self._entries.values())

    def _entries_for_capability(self, capability_id: str) -> tuple[RegistryEntry, ...]:
        return tuple(
            entry
            for entry in sorted(
                self._entries.values(),
                key=lambda entry: entry[0].implementation_id,
            )
            if entry[0].capability_id == capability_id
        )

    @staticmethod
    def _preflight_status(
        manifest: CapabilityManifest,
        model_id: str | None,
        mode: ExecutionMode,
        context: RuntimeIdentity,
    ) -> tuple[CapabilityStatus | None, ProbeObservation]:
        if not CapabilityRegistry._supports_request(manifest, model_id, mode):
            return CapabilityStatus.unsupported_route, CapabilityRegistry._failure_observation(
                "probe.unsupported_route", "model or execution mode is unsupported"
            )
        if manifest.model_scope is ModelScope.allowlist and model_id not in context.model_digests:
            return CapabilityStatus.missing_model_identity, CapabilityRegistry._failure_observation(
                "probe.missing_model_identity", "model identity is unavailable"
            )
        if manifest.platforms and context.platform not in manifest.platforms:
            return CapabilityStatus.incompatible_platform, CapabilityRegistry._failure_observation(
                "probe.incompatible_platform", "platform is unsupported"
            )
        if not set(manifest.runtime_requirements).issubset(context.runtime_ids):
            return CapabilityStatus.missing_runtime, CapabilityRegistry._failure_observation(
                "probe.missing_runtime", "required runtime is unavailable"
            )
        if not set(manifest.required_packages).issubset(context.installed_packages):
            return CapabilityStatus.missing_dependency, CapabilityRegistry._failure_observation(
                "probe.missing_dependency", "required dependency is unavailable"
            )
        return None, CapabilityRegistry._failure_observation("probe.pending", "functional probe pending")

    @staticmethod
    def _failure_observation(code: str, message: str) -> ProbeObservation:
        import hashlib

        digest = hashlib.sha256(f"{code}\0{message}".encode()).hexdigest()
        return ProbeObservation(
            succeeded=False,
            code=code,
            safe_message=message,
            evidence_digest=f"sha256:{digest}",
        )

    @staticmethod
    def _supports_request(
        manifest: CapabilityManifest, model_id: str | None, mode: ExecutionMode
    ) -> bool:
        if mode not in manifest.modes:
            return False
        if manifest.model_scope is ModelScope.independent:
            return True
        if model_id is None:
            return False
        models = manifest.native_models if mode is ExecutionMode.native else manifest.brokered_models
        return model_id in models

    @staticmethod
    def _request_models(request: Mapping[str, object]) -> tuple[str | None, str | None]:
        requested = request.get("requested_model_id", request.get("model_id"))
        effective = request.get("effective_model_id", requested)
        for field, value in (("requested_model_id", requested), ("effective_model_id", effective)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"request requires a non-empty {field} when provided")
        return requested, effective

    @staticmethod
    def _readiness_key(
        manifest: CapabilityManifest,
        requested_model_id: str | None,
        effective_model_id: str | None,
        mode: ExecutionMode,
        context: RuntimeIdentity,
    ) -> ReadinessKey:
        return (
            manifest.implementation_id,
            manifest.manifest_digest,
            requested_model_id,
            effective_model_id,
            context.model_digests.get(effective_model_id) if effective_model_id else None,
            mode,
            context.platform,
            context.runtime_ids,
            context.installed_packages,
            context.runtime_fingerprint,
            context.hardware_profile_id,
            context.hardware_fingerprint,
        )

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
