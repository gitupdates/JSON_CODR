from __future__ import annotations

import json
import asyncio
import shutil
from pathlib import Path
from uuid import uuid7

from web_app.core.rea_acquisition import ReaAcquirer, ReaReleaseMetadata
from web_app.core.rea_provider_state import ReaActivation, ReaProviderStore


class ReaUpdateService:
    def __init__(self, root: str | Path, store: ReaProviderStore, acquirer, verifier) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.acquirer = acquirer
        self.verifier = verifier
        self._update_lock = asyncio.Lock()

    async def reinstall(self, metadata: ReaReleaseMetadata, *, approved: bool = False) -> ReaActivation:
        async with self._update_lock:
            return await self._reinstall_locked(metadata, approved=approved)

    async def _reinstall_locked(self, metadata: ReaReleaseMetadata, *, approved: bool) -> ReaActivation:
        current = self.store.active()
        if current is not None and current.version == metadata.version:
            candidate = self.store.candidate(metadata.version)
            if candidate.state == "active" and not self._is_acquired(metadata):
                await asyncio.to_thread(self.acquirer.reconcile, metadata)
                await self.verifier.verify(metadata.version)
            if candidate.state == "active" and self._is_acquired(metadata):
                self._write_projection(current)
                return current
        if current is not None:
            current_major = int(current.version.split(".", 1)[0])
            candidate_major = int(metadata.version.split(".", 1)[0])
            if candidate_major != current_major and not approved:
                raise PermissionError("REA major-version activation requires explicit approval")
            if self._version_tuple(metadata.version) < self._version_tuple(current.version) and not approved:
                raise PermissionError("REA downgrade activation requires explicit approval")
        if not self._is_acquired(metadata):
            await asyncio.to_thread(self.acquirer.acquire, metadata)
        candidate = self.store.candidate(metadata.version)
        if candidate.state in {"staged", "quarantined"}:
            await self.verifier.verify(metadata.version)
        candidate = self.store.candidate(metadata.version)
        if candidate.state != "ready":
            raise RuntimeError(f"REA {metadata.version} did not complete verification")
        generation = 0 if current is None else current.generation
        activation = self.store.activate(metadata.version, expected_generation=generation)
        self._write_projection(activation)
        return activation

    def rollback(self, generation: int, reason: str) -> ReaActivation:
        activation = self.store.record_canary_failure(generation, reason)
        self._write_projection(activation)
        return activation

    def recover(self):
        recovered = self.store.recover()
        if hasattr(self.acquirer, "recover_staging"):
            self.acquirer.recover_staging()
        active = self.store.active()
        if active is not None:
            self._write_projection(active)
        return recovered

    def prune(self) -> tuple[str, ...]:
        removed = []
        versions_root = (self.root / "versions").resolve()
        for version in self.store.removable_versions():
            target = (versions_root / version).resolve()
            target.relative_to(versions_root)
            if target.is_dir():
                shutil.rmtree(target)
            removed.append(version)
        return tuple(removed)

    def _write_projection(self, activation: ReaActivation) -> None:
        target = self.root / "active.json"
        temporary = self.root / f"active.json.{uuid7()}.tmp"
        temporary.write_text(
            json.dumps({"generation": activation.generation, "version": activation.version}, sort_keys=True),
            encoding="utf-8",
        )
        current = self.store.active()
        if current is None or current.generation != activation.generation or current.version != activation.version:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("REA activation changed before projection commit")
        temporary.replace(target)

    def _is_acquired(self, metadata: ReaReleaseMetadata) -> bool:
        manifest_path = self.root / "versions" / metadata.version / "manifest.json"
        if not manifest_path.is_file():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        matches = (
            manifest.get("package") == metadata.package
            and manifest.get("version") == metadata.version
            and manifest.get("integrity") == metadata.integrity
            and manifest.get("registry") == metadata.registry
        )
        if not matches or not isinstance(manifest.get("package_tree_digest"), str):
            return False
        installation = manifest_path.parent / "installation"
        try:
            actual = ReaAcquirer._tree_digest(installation)
        except (OSError, RuntimeError):
            return False
        return actual == manifest["package_tree_digest"]

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, int, int]:
        core = version.split("-", 1)[0]
        return tuple(int(part) for part in core.split("."))
