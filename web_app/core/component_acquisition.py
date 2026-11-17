from __future__ import annotations

import hashlib
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid7

from web_app.core.contracts import FrozenContract
from web_app.core.component_registry import ComponentRequest, ComponentSource
from web_app.core.component_normalization import build_normalization_report


class AcquiredComponent(FrozenContract):
    source_kind: ComponentSource
    canonical_source: str
    source_root: str
    content_digest: str
    revision: str | None = None
    requested_version: str | None = None


_PYTHON_COORDINATE = re.compile(r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)==(?P<version>[0-9][A-Za-z0-9.!+_-]*)$")
_NODE_COORDINATE = re.compile(
    r"^(?P<name>(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*)@"
    r"(?P<version>0|[1-9][0-9]*)(?:\.(?P<minor>0|[1-9][0-9]*))"
    r"(?:\.(?P<patch>0|[1-9][0-9]*))(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def parse_package_coordinate(kind: ComponentSource, coordinate: str) -> tuple[str, str]:
    """Return a normalized package name and an exact version."""
    if kind is ComponentSource.python:
        match = _PYTHON_COORDINATE.fullmatch(coordinate)
        if match:
            name = re.sub(r"[-_.]+", "-", match.group("name")).casefold()
            return name, match.group("version")
    elif kind is ComponentSource.node:
        match = _NODE_COORDINATE.fullmatch(coordinate)
        if match:
            version = match.group("version") + "." + match.group("minor") + "." + match.group("patch")
            suffix = coordinate[coordinate.rfind("@") + 1 :]
            version = suffix if suffix.startswith(version) else version
            return match.group("name").casefold(), version
    raise ValueError("package coordinates require an exact package name and exact version")


class ComponentAcquirer:
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
        if request.source_kind is ComponentSource.python:
            return self._python(request, target)
        if request.source_kind is ComponentSource.node:
            return self._node(request, target)
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

    def _python(self, request: ComponentRequest, target: Path) -> AcquiredComponent:
        name, version = parse_package_coordinate(ComponentSource.python, request.source)
        coordinate = f"{name}=={version}"
        artifacts = target / "artifacts"
        artifacts.mkdir(parents=True)
        command = [
            sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
            "--isolated", "--only-binary=:all:", "--dest", str(artifacts),
            "--index-url", "https://pypi.org/simple/", coordinate,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300, env=_sanitized_environment())
        if completed.returncode:
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        _enforce_tree_limits(target)
        wheels = sorted(artifacts.iterdir())
        if not wheels or any(path.suffix.casefold() != ".whl" for path in wheels):
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError("Python package resolution produced a non-wheel artifact")
        resolved = [_wheel_record(path) for path in wheels]
        root_record = next((item for item in resolved if _normalize_python_name(item["name"]) == name), None)
        if root_record is None or root_record["version"] != version:
            raise ValueError("Python registry returned a package that did not match the exact coordinate")
        manifest = {
            "format": 1, "ecosystem": "python", "registry": "https://pypi.org/simple/",
            "coordinate": coordinate, "artifacts": resolved, "entry_points": root_record["entry_points"],
        }
        (target / "component-resolution.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        (target / "component-normalization.json").write_text(
            json.dumps(build_normalization_report(manifest), indent=2, sort_keys=True), encoding="utf-8"
        )
        return AcquiredComponent(
            source_kind=request.source_kind, canonical_source=coordinate, source_root=str(target),
            content_digest=_tree_digest(target), requested_version=version,
        )

    def _node(self, request: ComponentRequest, target: Path) -> AcquiredComponent:
        name, version = parse_package_coordinate(ComponentSource.node, request.source)
        coordinate = f"{name}@{version}"
        target.mkdir()
        (target / "package.json").write_text(
            json.dumps({"name": "json-codr-component", "private": True, "dependencies": {name: version}}),
            encoding="utf-8",
        )
        npmrc = target / ".npmrc"
        npmrc.write_text("registry=https://registry.npmjs.org/\nignore-scripts=true\n", encoding="utf-8")
        cache = target / ".npm-cache"
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if npm is None:
            raise RuntimeError("npm is required to resolve Node package coordinates")
        command = [
            npm, "install", "--ignore-scripts", "--no-audit", "--no-fund", "--package-lock=true",
            "--registry=https://registry.npmjs.org/", "--userconfig", str(npmrc), "--cache", str(cache),
        ]
        completed = subprocess.run(command, cwd=target, capture_output=True, text=True, timeout=300, env=_sanitized_environment())
        if completed.returncode:
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        _enforce_tree_limits(target)
        package_root = target / "node_modules" / Path(*name.split("/"))
        package_json = package_root / "package.json"
        if not package_json.is_file():
            raise ValueError("npm registry did not materialize the exact requested package")
        document = json.loads(package_json.read_text(encoding="utf-8"))
        if str(document.get("name", "")).casefold() != name or document.get("version") != version:
            raise ValueError("npm registry returned a package that did not match the exact coordinate")
        bins = document.get("bin", {})
        if isinstance(bins, str):
            bins = {name.rsplit("/", 1)[-1]: bins}
        entries = {}
        for command_name, relative in bins.items():
            candidate = (package_root / str(relative)).resolve()
            try:
                candidate.relative_to(package_root.resolve())
            except ValueError as error:
                raise ValueError("npm bin target escapes its package") from error
            entries[str(command_name)] = candidate.relative_to(target).as_posix()
        lock = json.loads((target / "package-lock.json").read_text(encoding="utf-8"))
        packages = []
        for package_path, record in lock.get("packages", {}).items():
            if not package_path or not isinstance(record, dict) or record.get("link"):
                continue
            resolved = str(record.get("resolved", ""))
            integrity = str(record.get("integrity", ""))
            if not resolved.startswith("https://registry.npmjs.org/") or not integrity.startswith("sha512-"):
                raise ValueError("npm dependency lacks public-registry integrity metadata")
            inferred_name = package_path.rsplit("node_modules/", 1)[-1].replace("\\", "/")
            packages.append({
                "name": str(record.get("name") or inferred_name), "version": str(record.get("version", "")),
                "resolved": resolved, "integrity": integrity,
            })
        manifest = {
            "format": 1, "ecosystem": "node", "registry": "https://registry.npmjs.org/",
            "coordinate": coordinate, "lock_sha256": _file_sha256(target / "package-lock.json"),
            "entry_points": entries, "packages": packages,
        }
        shutil.rmtree(cache, ignore_errors=True)
        npmrc.unlink(missing_ok=True)
        (target / "component-resolution.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        (target / "component-normalization.json").write_text(
            json.dumps(build_normalization_report(manifest), indent=2, sort_keys=True), encoding="utf-8"
        )
        return AcquiredComponent(
            source_kind=request.source_kind, canonical_source=coordinate, source_root=str(target),
            content_digest=_tree_digest(target), requested_version=version,
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


def _enforce_tree_limits(root: Path, *, max_files: int = 50_000, max_bytes: int = 512 * 1024 * 1024) -> None:
    files = 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            files += 1
            if files > max_files:
                raise ValueError("package staging exceeded the file-count limit")
            total += path.stat().st_size
            if total > max_bytes:
                raise ValueError("package staging exceeded the expanded-size limit")


def _normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_record(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 10_000 or sum(item.file_size for item in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("wheel exceeds archive safety limits")
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata_info = archive.getinfo(metadata_name)
        if metadata_info.file_size > 1024 * 1024:
            raise ValueError("wheel metadata exceeds the size limit")
        metadata = {}
        for line in archive.read(metadata_name).decode("utf-8", errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata.setdefault(key.casefold(), value.strip())
        entry_points = {}
        entries_name = metadata_name.rsplit("/", 1)[0] + "/entry_points.txt"
        if entries_name in archive.namelist():
            if archive.getinfo(entries_name).file_size > 1024 * 1024:
                raise ValueError("wheel entry-point metadata exceeds the size limit")
            parser = configparser.ConfigParser()
            parser.optionxform = str
            parser.read_string(archive.read(entries_name).decode("utf-8"))
            if parser.has_section("console_scripts"):
                entry_points = dict(parser.items("console_scripts"))
    return {
        "filename": path.name, "sha256": _file_sha256(path), "name": metadata["name"],
        "version": metadata["version"], "entry_points": entry_points,
    }


def _sanitized_environment() -> dict[str, str]:
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}
