from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.contracts import FrozenContract
from web_app.models import SkillPack


class ComponentManifest(FrozenContract):
    component_id: str
    kind: str
    source: str
    content_digest: str


class ProvenanceRecord(FrozenContract):
    component_id: str
    source: str
    content_digest: str
    staged_path: str
    probe_evidence: str | None = None


class QuarantineRecord(FrozenContract):
    component_id: str
    state: str
    project_ids: tuple[str, ...] = ()
    global_enabled: bool = False
    reason: str | None = None


class FunctionalProbeResult(FrozenContract):
    success: bool
    evidence: str | None = None
    reason: str | None = None


class AssimilationService:
    def __init__(self, root: str | Path, probe) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._probe = probe
        self._records: dict[str, QuarantineRecord] = {}
        self._provenance: dict[str, ProvenanceRecord] = {}

    def identify(self, source: str | Path) -> ComponentManifest:
        path = Path(source).resolve()
        payload = path.read_bytes()
        if path.name.casefold() == "skill.md":
            kind = "skill"
        elif path.suffix.casefold() in {".zip", ".7z"}:
            kind = "archive"
        elif path.suffix.casefold() == ".json":
            kind = "mcp"
        else:
            kind = "resource"
        return self.identify_payload(str(path), kind, payload)

    def identify_payload(self, source: str, kind: str, payload: bytes) -> ComponentManifest:
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        return ComponentManifest(
            component_id=f"{kind}-{digest.removeprefix('sha256:')[:16]}",
            kind=kind,
            source=source,
            content_digest=digest,
        )

    async def install(self, manifest: ComponentManifest) -> QuarantineRecord:
        return await self.install_payload(manifest, Path(manifest.source).read_bytes())

    async def install_payload(self, manifest: ComponentManifest, payload: bytes) -> QuarantineRecord:
        existing = self._records.get(manifest.component_id)
        if existing is not None:
            return existing
        staged = self.root / "quarantine" / manifest.component_id
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True, exist_ok=False)
        source_name = Path(manifest.source).name or "component.bin"
        target = staged / source_name
        target.write_bytes(payload)
        self._records[manifest.component_id] = QuarantineRecord(
            component_id=manifest.component_id, state="quarantined"
        )
        probe_value = FunctionalProbeResult.model_validate(await self._probe(manifest, staged))
        record = QuarantineRecord(
            component_id=manifest.component_id,
            state="verified" if probe_value.success else "quarantined",
            reason=probe_value.reason,
        )
        self._records[manifest.component_id] = record
        self._provenance[manifest.component_id] = ProvenanceRecord(
            component_id=manifest.component_id,
            source=manifest.source,
            content_digest=manifest.content_digest,
            staged_path=str(staged),
            probe_evidence=probe_value.evidence,
        )
        return record

    def status(self, component_id: str) -> QuarantineRecord:
        return self._records[component_id]

    def provenance(self, component_id: str) -> ProvenanceRecord:
        return self._provenance[component_id]

    def enable(self, component_id: str, *, project_id: str) -> QuarantineRecord:
        record = self.status(component_id)
        if record.state != "verified":
            raise PermissionError("component has not passed its functional probe")
        updated = record.model_copy(update={"project_ids": tuple(dict.fromkeys((*record.project_ids, project_id)))})
        self._records[component_id] = updated
        return updated

    def promote(self, component_id: str) -> QuarantineRecord:
        record = self.status(component_id)
        if record.state != "verified":
            raise PermissionError("component has not passed its functional probe")
        updated = record.model_copy(update={"global_enabled": True})
        self._records[component_id] = updated
        return updated

    def remove(self, component_id: str) -> None:
        provenance = self._provenance.pop(component_id)
        self._records.pop(component_id)
        shutil.rmtree(provenance.staged_path)


class SkillInstallAdapter:
    def __init__(
        self,
        assimilation: AssimilationService,
        resolve: Callable[[str, dict], tuple[SkillPack, Callable[[], None]]],
        install: Callable[[SkillPack], SkillPack],
        duplicate_error: type[Exception],
    ) -> None:
        self._assimilation = assimilation
        self._resolve = resolve
        self._install = install
        self._duplicate_error = duplicate_error

    async def execute(self, call: CapabilityCall, context: ExecutionContext) -> AsyncIterator[AdapterEvent]:
        if call.operation != "install":
            raise CapabilityExecutionError("invalid_request", "Unsupported component operation")
        source_kind = str(call.arguments.get("source_kind", ""))
        reference = dict(call.arguments.get("reference", {}))
        cleanup = lambda: None
        try:
            pack, cleanup = self._resolve(source_kind, reference)
            payload = json.dumps(pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
            manifest = self._assimilation.identify_payload(pack.source_name, "skill-pack", payload)
            record = await self._assimilation.install_payload(manifest, payload)
            if record.state != "verified":
                raise CapabilityExecutionError(
                    "component_probe_failed", record.reason or "Component functional probe failed"
                )
            installed = self._install(pack)
            yield AdapterEvent(event_type="component.installed", payload={
                "source_kind": source_kind,
                "component_id": manifest.component_id,
                "provenance": self._assimilation.provenance(manifest.component_id).model_dump(mode="json"),
                "result": installed.model_dump(mode="json"),
            })
        except self._duplicate_error as error:
            raise CapabilityExecutionError("component_duplicate", str(error)) from error
        except ValueError as error:
            raise CapabilityExecutionError("invalid_request", str(error)) from error
        finally:
            cleanup()
