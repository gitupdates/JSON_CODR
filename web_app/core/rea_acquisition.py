from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid7

from web_app.core.rea_provider_state import ReaProviderStore


_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class ReaReleaseMetadata:
    package: str
    version: str
    integrity: str
    registry: str
    tarball: str


class NpmReaInstaller:
    def __init__(self, npm: str = "npm.cmd") -> None:
        self.npm = npm

    def install(self, metadata: ReaReleaseMetadata, installation: Path) -> None:
        installation.mkdir(parents=True, exist_ok=False)
        result = subprocess.run(
            [
                self.npm, "install", "--prefix", str(installation), "--save-exact",
                "--registry", metadata.registry, "--no-audit", "--no-fund",
                f"{metadata.package}@{metadata.version}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        (installation.parent / "npm-output.log").write_text(
            self._redact(result.stdout + ("\n" + result.stderr if result.stderr else "")), encoding="utf-8"
        )
        if result.returncode != 0:
            raise RuntimeError(f"npm REA installation failed with exit code {result.returncode}")


class ReaAcquirer:
    def __init__(self, root: str | Path, store: ReaProviderStore, installer) -> None:
        self.root = Path(root).resolve()
        self.store = store
        self.installer = installer
        self.versions = self.root / "versions"
        self.staging = self.root / "staging"
        self.versions.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def acquire(self, metadata: ReaReleaseMetadata) -> Path:
        self._validate_metadata(metadata)
        target = self._contained(self.versions / metadata.version, self.versions)
        try:
            candidate = self.store.candidate(metadata.version)
        except KeyError:
            candidate = self.store.discover(metadata.version, integrity=metadata.integrity, source=metadata.registry)
        else:
            if candidate.integrity != metadata.integrity or candidate.source != metadata.registry:
                raise ValueError("REA package identity changed for an existing version")
            if candidate.state == "acquiring":
                raise RuntimeError(f"REA {metadata.version} acquisition is already in progress")
            if candidate.state in {"staged", "verifying", "ready", "active", "draining", "rolled_back"}:
                if not target.is_dir():
                    raise RuntimeError("durable REA state references a missing version directory")
                return target
        candidate = self.store.transition(metadata.version, "acquiring", expected_revision=candidate.revision)
        stage = self._contained(self.staging / f"{metadata.version}-{uuid7()}", self.staging)
        try:
            stage.mkdir(parents=True, exist_ok=False)
            installation = stage / "installation"
            self.installer.install(metadata, installation)
            package_json = installation / "node_modules" / "rea-agents" / "package.json"
            if not package_json.is_file():
                raise RuntimeError("installed REA package is missing package.json")
            package = json.loads(package_json.read_text(encoding="utf-8"))
            if package.get("name") != metadata.package or package.get("version") != metadata.version:
                raise RuntimeError("installed REA package identity does not match requested release")
            self._verify_lock_identity(installation / "package-lock.json", metadata)
            self._reject_escaped_entries(installation)
            manifest = {**asdict(metadata), "package_tree_digest": self._tree_digest(installation)}
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            lock = installation / "package-lock.json"
            if lock.is_file():
                shutil.copy2(lock, stage / "package-lock.json")
            if target.exists():
                raise RuntimeError("REA version directory already exists")
            stage.replace(target)
            self.store.transition(metadata.version, "staged", expected_revision=candidate.revision)
            return target
        except BaseException:
            if stage.exists():
                shutil.rmtree(stage)
            current = self.store.candidate(metadata.version)
            if current.state == "acquiring":
                self.store.transition(metadata.version, "quarantined", expected_revision=current.revision)
            raise

    @staticmethod
    def _validate_metadata(metadata: ReaReleaseMetadata) -> None:
        if metadata.package != "rea-agents":
            raise ValueError("only the rea-agents package is accepted")
        if not _VERSION.fullmatch(metadata.version):
            raise ValueError("REA release must be an exact semantic version")
        if not metadata.integrity:
            raise ValueError("npm integrity is required")
        if metadata.registry.rstrip("/") != "https://registry.npmjs.org":
            raise ValueError("untrusted npm registry")

    @staticmethod
    def _contained(path: Path, root: Path) -> Path:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        return resolved

    @staticmethod
    def _tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        lock = root / "package-lock.json"
        if not lock.is_file():
            raise RuntimeError("npm installation is missing package-lock.json")
        digest.update(lock.read_bytes())
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _verify_lock_identity(lock_path: Path, metadata: ReaReleaseMetadata) -> None:
        if not lock_path.is_file():
            raise RuntimeError("npm installation is missing package-lock.json")
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        package = lock.get("packages", {}).get("node_modules/rea-agents", {})
        if package.get("version") != metadata.version:
            raise RuntimeError("npm lockfile REA version does not match requested release")
        if package.get("integrity") != metadata.integrity:
            raise RuntimeError("npm lockfile integrity does not match discovered release")
        if package.get("resolved") != metadata.tarball:
            raise RuntimeError("npm lockfile tarball does not match discovered release")

    @staticmethod
    def _reject_escaped_entries(root: Path) -> None:
        resolved_root = root.resolve()
        for path in root.rglob("*"):
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            if path.is_symlink() or attributes & getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise RuntimeError(f"provider package contains a link or reparse point: {path.relative_to(root)}")
            path.resolve().relative_to(resolved_root)

    @staticmethod
    def _redact(output: str) -> str:
        output = re.sub(r"(?i)(token|password|secret|authorization)=([^\s]+)", r"\1=<redacted>", output)
        return re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1<redacted>@", output)

    def recover_staging(self) -> tuple[Path, ...]:
        removed = []
        for path in self.staging.iterdir():
            contained = self._contained(path, self.staging)
            if contained.is_dir():
                shutil.rmtree(contained)
            else:
                contained.unlink()
            removed.append(contained)
        return tuple(removed)

    def reconcile(self, metadata: ReaReleaseMetadata) -> Path:
        self._validate_metadata(metadata)
        target = self._contained(self.versions / metadata.version, self.versions)
        installation = target / "installation"
        package_json = installation / "node_modules" / "rea-agents" / "package.json"
        if not package_json.is_file():
            raise RuntimeError("existing REA installation is missing package identity")
        package = json.loads(package_json.read_text(encoding="utf-8"))
        if package.get("name") != metadata.package or package.get("version") != metadata.version:
            raise RuntimeError("existing REA installation identity mismatch")
        self._verify_lock_identity(installation / "package-lock.json", metadata)
        self._reject_escaped_entries(installation)
        manifest = {**asdict(metadata), "package_tree_digest": self._tree_digest(installation)}
        temporary = target / "manifest.json.tmp"
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(target / "manifest.json")
        return target
