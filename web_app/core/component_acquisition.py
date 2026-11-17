from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid7

from web_app.core.contracts import FrozenContract
from web_app.core.component_registry import ComponentRequest, ComponentSource


class AcquiredComponent(FrozenContract):
    source_kind: ComponentSource
    canonical_source: str
    source_root: str
    content_digest: str
    revision: str | None = None
    requested_version: str | None = None


class ComponentAcquirer:
    _package_coordinate = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*(?:==|@)?[A-Za-z0-9.+_-]*$")

    def acquire(self, request: ComponentRequest, staging_root: str | Path) -> AcquiredComponent:
        root = Path(staging_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"acquire-{uuid7()}"
        if request.source_kind is ComponentSource.git:
            return self._git(request, target)
        if request.source_kind in {ComponentSource.local, ComponentSource.executable, ComponentSource.mcp}:
            return self._local(request, target)
        if request.source_kind is ComponentSource.archive:
            return self._archive(request, target)
        if request.source_kind in {ComponentSource.python, ComponentSource.node}:
            return self._package(request, target)
        raise ValueError(f"unsupported component source: {request.source_kind.value}")

    def _git(self, request: ComponentRequest, target: Path) -> AcquiredComponent:
        source_path = Path(request.source)
        if source_path.exists():
            source = str(source_path.resolve())
        else:
            parsed = urlparse(request.source)
            if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
                raise ValueError("Git sources must be local paths or public HTTPS URLs")
            source = request.source
        result = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", "--", source, str(target)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Git acquisition failed: {(result.stderr or result.stdout).strip()}")
        revision = request.requested_version or "HEAD"
        checkout = subprocess.run(
            ["git", "checkout", "--quiet", "--detach", revision],
            cwd=target,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if checkout.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError(f"Git revision is unavailable: {revision}")
        resolved = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
        return AcquiredComponent(
            source_kind=request.source_kind,
            canonical_source=source,
            source_root=str(target),
            content_digest=_tree_digest(target, exclude={".git"}),
            revision=resolved,
            requested_version=request.requested_version,
        )

    def _local(self, request: ComponentRequest, target: Path) -> AcquiredComponent:
        source = Path(request.source).resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.mkdir()
            shutil.copy2(source, target / source.name)
        return AcquiredComponent(
            source_kind=request.source_kind,
            canonical_source=str(source),
            source_root=str(target),
            content_digest=_tree_digest(target),
            requested_version=request.requested_version,
        )

    def _archive(self, request: ComponentRequest, target: Path) -> AcquiredComponent:
        source = Path(request.source).resolve()
        if source.suffix.casefold() != ".zip" or not source.is_file():
            raise ValueError("initial component archive support requires a local .zip file")
        target.mkdir()
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                destination = (target / info.filename).resolve()
                try:
                    destination.relative_to(target)
                except ValueError as error:
                    shutil.rmtree(target, ignore_errors=True)
                    raise ValueError("unsafe archive path") from error
                if Path(info.filename).is_absolute() or ".." in Path(info.filename).parts:
                    shutil.rmtree(target, ignore_errors=True)
                    raise ValueError("unsafe archive path")
            archive.extractall(target)
        return AcquiredComponent(
            source_kind=request.source_kind,
            canonical_source=str(source),
            source_root=str(target),
            content_digest=_tree_digest(target),
            requested_version=request.requested_version,
        )

    def _package(self, request: ComponentRequest, target: Path) -> AcquiredComponent:
        if not self._package_coordinate.fullmatch(request.source):
            raise ValueError("invalid package coordinate")
        target.mkdir()
        coordinate = request.source + (f"@{request.requested_version}" if request.requested_version else "")
        (target / "component-coordinate.txt").write_text(coordinate, encoding="utf-8")
        return AcquiredComponent(
            source_kind=request.source_kind,
            canonical_source=request.source,
            source_root=str(target),
            content_digest=_tree_digest(target),
            requested_version=request.requested_version,
        )


def _tree_digest(root: Path, *, exclude: set[str] | None = None) -> str:
    excluded = exclude or set()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("symbolic links are not accepted in component sources")
        if path.is_file():
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            digest.update(b"\0")
    return "sha256:" + digest.hexdigest()
