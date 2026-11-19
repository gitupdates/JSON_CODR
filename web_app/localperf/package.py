from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from web_app.localperf.storage import LocalPerfStorage
from web_app.localperf.workload import CORE_WORKLOAD, WORKLOAD_NAME, WORKLOAD_VERSION, workload_hash

PACKAGE_VERSION = "1.0"
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_MEMBERS = 32
REQUIRED_MEMBERS = {
    "manifest.json", "standard/workload.json", "standard/localperf_run.schema.json",
    "standard/METHOD.md", "standard/REPORT-TEMPLATE.md",
    "reference/aggregate.json", "reference/samples.jsonl",
}


class LocalPerfPackageError(ValueError):
    pass


@dataclass(frozen=True)
class PackageArtifact:
    filename: str
    content: bytes


@dataclass(frozen=True)
class PackagePreview:
    valid: bool
    package_id: str
    evaluation_id: str
    contains_system_details: bool
    members: tuple[str, ...]


@dataclass(frozen=True)
class ImportRecord:
    package_id: str
    path: Path
    retained_system_details: bool


class LocalPerfPackageService:
    def __init__(self, storage: LocalPerfStorage):
        self.storage = storage
        self.assets = Path(__file__).resolve().parent

    def _run_directory(self, evaluation_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", evaluation_id):
            raise LocalPerfPackageError("Invalid evaluation ID")
        directory = (self.storage.runs_root / evaluation_id).resolve()
        if directory.parent != self.storage.runs_root.resolve() or not directory.is_dir():
            raise LocalPerfPackageError("Evaluation was not found")
        return directory

    @staticmethod
    def _sanitize(aggregate: dict) -> dict:
        result = copy.deepcopy(aggregate)
        configuration = result["configuration"]
        hardware = configuration.get("hardware", {})
        software = configuration.get("software", {})
        configuration["hardware"] = {"sanitized": True, "kind": hardware.get("kind", configuration.get("backend", "unknown"))}
        configuration["software"] = {"sanitized": True, "application": software.get("application", "JSON_CODR"), "version": software.get("version", "unknown")}
        configuration["hash"] = hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result["privacy"] = {"system_details_included": False, "sanitized": True}
        return result

    def export(self, evaluation_id: str, include_system_details: bool = False) -> PackageArtifact:
        directory = self._run_directory(evaluation_id)
        aggregate = json.loads((directory / "aggregate.json").read_text(encoding="utf-8"))
        if not include_system_details:
            aggregate = self._sanitize(aggregate)
        else:
            aggregate["privacy"] = {"system_details_included": True, "sanitized": False}
        workload = {
            "name": WORKLOAD_NAME, "version": WORKLOAD_VERSION, "hash": workload_hash(),
            "prompts": [item.__dict__ for item in CORE_WORKLOAD],
        }
        members = {
            "standard/workload.json": json.dumps(workload, indent=2, ensure_ascii=False).encode(),
            "standard/localperf_run.schema.json": (self.assets.parent.parent / "docs" / "user" / "localperf_run.schema.json").read_bytes(),
            "standard/METHOD.md": (self.assets / "METHOD.md").read_bytes(),
            "standard/REPORT-TEMPLATE.md": (self.assets / "REPORT-TEMPLATE.md").read_bytes(),
            "reference/aggregate.json": json.dumps(aggregate, indent=2, ensure_ascii=False).encode(),
            "reference/samples.jsonl": (directory / "samples.jsonl").read_bytes(),
        }
        checksums = {name: hashlib.sha256(content).hexdigest() for name, content in members.items()}
        created = datetime.now(timezone.utc)
        manifest = {
            "package_version": PACKAGE_VERSION, "schema_version": "0.3.0-localperf",
            "workload_name": WORKLOAD_NAME, "workload_version": WORKLOAD_VERSION,
            "workload_hash": workload_hash(), "created_at": created.isoformat(),
            "include_system_details": include_system_details, "evaluation_id": evaluation_id,
            "checksums": checksums, "results": [evaluation_id],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2).encode())
            for name, content in members.items():
                archive.writestr(name, content)
        filename = f"json-codr-localperf-core-v1-{WORKLOAD_VERSION}-{created.strftime('%Y%m%dT%H%M%SZ')}.localperf.zip"
        return PackageArtifact(filename=filename, content=buffer.getvalue())

    def _validated_members(self, payload: bytes) -> tuple[dict, dict[str, bytes]]:
        if len(payload) > MAX_PACKAGE_BYTES:
            raise LocalPerfPackageError("Package exceeds the size limit")
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as error:
            raise LocalPerfPackageError("Invalid LocalPerf ZIP") from error
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) > MAX_MEMBERS or len(names) != len(set(names)):
            raise LocalPerfPackageError("Invalid member count or duplicate name")
        for info in infos:
            path = PurePosixPath(info.filename)
            mode = info.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or stat.S_ISLNK(mode):
                raise LocalPerfPackageError("Unsafe archive member path or link")
            if info.file_size > MAX_MEMBER_BYTES or info.is_dir() or info.filename.lower().endswith((".exe", ".dll", ".ps1", ".bat", ".cmd", ".py")):
                raise LocalPerfPackageError("Unsupported or oversized archive member")
        if set(names) != REQUIRED_MEMBERS:
            raise LocalPerfPackageError("Package members do not match the LocalPerf standard")
        members = {name: archive.read(name) for name in names}
        try:
            manifest = json.loads(members["manifest.json"])
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise LocalPerfPackageError("Invalid manifest") from error
        if manifest.get("package_version") != PACKAGE_VERSION or manifest.get("schema_version") != "0.3.0-localperf" or manifest.get("workload_hash") != workload_hash():
            raise LocalPerfPackageError("Incompatible package, schema, or workload version")
        expected = manifest.get("checksums", {})
        for name in REQUIRED_MEMBERS - {"manifest.json"}:
            if expected.get(name) != hashlib.sha256(members[name]).hexdigest():
                raise LocalPerfPackageError(f"Package checksum mismatch: {name}")
        return manifest, members

    def preview(self, payload: bytes) -> PackagePreview:
        manifest, members = self._validated_members(payload)
        aggregate = json.loads(members["reference/aggregate.json"])
        details = bool(manifest.get("include_system_details") or aggregate.get("privacy", {}).get("system_details_included"))
        return PackagePreview(True, hashlib.sha256(payload).hexdigest(), manifest["evaluation_id"], details, tuple(sorted(members)))

    def import_package(self, payload: bytes, retain_system_details: bool = False) -> ImportRecord:
        manifest, members = self._validated_members(payload)
        contains_details = bool(manifest.get("include_system_details"))
        if contains_details and not retain_system_details:
            raise LocalPerfPackageError("Explicit consent is required to retain system details")
        package_id = hashlib.sha256(payload).hexdigest()
        imports = self.storage.data_root / "localperf" / "imports"
        destination = imports / package_id
        if destination.exists():
            return ImportRecord(package_id, destination, contains_details and retain_system_details)
        temporary = imports / f".{package_id}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            for name, content in members.items():
                path = temporary.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                if name == "reference/aggregate.json":
                    aggregate = json.loads(content)
                    aggregate["source"] = "imported"
                    aggregate["eligible_as_local_baseline"] = False
                    content = json.dumps(aggregate, indent=2).encode()
                path.write_bytes(content)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return ImportRecord(package_id, destination, contains_details and retain_system_details)
