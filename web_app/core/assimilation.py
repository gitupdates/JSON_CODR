from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from web_app.core.contracts import FrozenContract


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
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if path.name.casefold() == "skill.md":
            kind = "skill"
        elif path.suffix.casefold() in {".zip", ".7z"}:
            kind = "archive"
        elif path.suffix.casefold() == ".json":
            kind = "mcp"
        else:
            kind = "resource"
        return ComponentManifest(
            component_id=f"{kind}-{digest.removeprefix('sha256:')[:16]}",
            kind=kind,
            source=str(path),
            content_digest=digest,
        )

    async def install(self, manifest: ComponentManifest) -> QuarantineRecord:
        existing = self._records.get(manifest.component_id)
        if existing is not None:
            return existing
        staged = self.root / "quarantine" / manifest.component_id
        staged.mkdir(parents=True, exist_ok=False)
        source = Path(manifest.source)
        target = staged / source.name
        shutil.copy2(source, target)
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
