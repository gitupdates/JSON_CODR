from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen
from uuid import uuid7

from pydantic import Field

from web_app.core.canonical import canonical_digest, canonical_json
from web_app.core.contracts import FrozenContract


class IsolationUnavailable(RuntimeError):
    """The configured restricted execution boundary cannot be established."""


class MaterializedBuild(FrozenContract):
    candidate_id: str
    revision: str
    tree_sha: str
    update_profile_digest: str
    verification_profile_digest: str
    version: str
    root: str
    artifact_digest: str


class BuildManifest(FrozenContract):
    candidate_id: str
    revision: str
    tree_sha: str
    update_profile_digest: str
    verification_profile_digest: str
    version: str
    migration_compatibility: str
    artifact_root: str
    artifact_digest: str
    container_image: str
    launch_argv: tuple[str, ...]
    container_port: int = Field(ge=1, le=65535)
    manifest_digest: str | None = None
    signature: str | None = None


class BuildManifestSigner:
    """Authenticates every immutable input used by the health boundary."""

    def __init__(self, *, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("build manifest signing key must contain at least 32 bytes")
        self._key = bytes(key)

    @staticmethod
    def _material(manifest: BuildManifest) -> dict[str, Any]:
        return manifest.model_dump(
            mode="json", exclude={"manifest_digest", "signature"}
        )

    def sign(self, manifest: BuildManifest) -> BuildManifest:
        material = self._material(manifest)
        digest = canonical_digest(material)
        signature = "hmac-sha256:" + hmac.new(
            self._key, canonical_json(material), hashlib.sha256
        ).hexdigest()
        return manifest.model_copy(update={
            "manifest_digest": digest,
            "signature": signature,
        })

    def validate(self, manifest: BuildManifest) -> bool:
        if not manifest.manifest_digest or not manifest.signature:
            return False
        material = self._material(manifest)
        expected_digest = canonical_digest(material)
        expected_signature = "hmac-sha256:" + hmac.new(
            self._key, canonical_json(material), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(manifest.manifest_digest, expected_digest) and hmac.compare_digest(
            manifest.signature, expected_signature
        )


class ArtifactMaterializer:
    """Exports a verified commit into a metadata-free, immutable build directory."""

    def __init__(self, artifacts_root: str | Path) -> None:
        self.root = Path(artifacts_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _git(repository: Path, *arguments: str, binary: bool = False):
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
        )
        return result.stdout

    @staticmethod
    def _literal_version(root: Path) -> str:
        version_file = root / "web_app" / "version.py"
        tree = ast.parse(version_file.read_text(encoding="utf-8"), filename=str(version_file))
        for statement in tree.body:
            if (
                isinstance(statement, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in statement.targets)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                return statement.value.value
        raise PermissionError("candidate version is not a literal APP_VERSION assignment")

    @staticmethod
    def _extract_archive(archive: bytes, destination: Path) -> None:
        import io

        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
            for member in stream.getmembers():
                member_path = destination / member.name
                try:
                    member_path.resolve().relative_to(destination.resolve())
                except ValueError as error:
                    raise PermissionError("candidate archive contains a path traversal") from error
                if not (member.isdir() or member.isfile()):
                    raise PermissionError("candidate archive contains links or special files")
            stream.extractall(destination, filter="data")

    @staticmethod
    def _directory_digest(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            content = path.read_bytes()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()

    def materialize(self, candidate, profile) -> MaterializedBuild:
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        revision = str(getattr(candidate, "commit_sha", "") or "")
        receipt = getattr(candidate, "verification_receipt", None)
        repository_value = getattr(getattr(candidate, "worktree", None), "working_root", "")
        repository = Path(repository_value).resolve() if repository_value else Path()
        expected_profile_digest = canonical_digest(profile.model_dump(mode="json"))
        if not candidate_id or not revision or receipt is None or not repository.is_dir():
            raise PermissionError("candidate verified identity is incomplete")
        if getattr(candidate, "profile_digest", None) != expected_profile_digest:
            raise PermissionError("candidate update profile binding does not match")
        if receipt.candidate_id != candidate_id:
            raise PermissionError("candidate verification receipt identity does not match")
        head = self._git(repository, "rev-parse", "HEAD").strip()
        if head != revision:
            raise PermissionError("candidate HEAD does not match the verified commit")
        tree_sha = self._git(repository, "rev-parse", f"{revision}^{{tree}}").strip()
        if tree_sha != receipt.tree_sha:
            raise PermissionError("candidate commit tree does not match the verification receipt tree")
        if self._git(repository, "status", "--porcelain").strip():
            raise PermissionError("candidate worktree changed after verification")

        artifact = self.root / candidate_id / revision
        artifact.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=artifact.parent))
        try:
            archive = self._git(repository, "archive", "--format=tar", revision, binary=True)
            self._extract_archive(archive, temporary)
            if (temporary / ".git").exists() or any(path.is_symlink() for path in temporary.rglob("*")):
                raise PermissionError("materialized candidate exposes repository metadata or links")
            version = self._literal_version(temporary)
            if version != getattr(profile, "expected_version", None):
                raise PermissionError("candidate version does not match the bound update profile")
            if artifact.exists():
                if (
                    not artifact.is_dir()
                    or artifact.is_symlink()
                    or self._directory_digest(artifact) != self._directory_digest(temporary)
                ):
                    raise PermissionError("existing immutable candidate artifact does not match the commit")
                shutil.rmtree(temporary)
            else:
                os.replace(temporary, artifact)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return MaterializedBuild(
            candidate_id=candidate_id,
            revision=revision,
            tree_sha=tree_sha,
            update_profile_digest=expected_profile_digest,
            verification_profile_digest=receipt.profile_digest,
            version=version,
            root=str(artifact),
            artifact_digest=self._directory_digest(artifact),
        )


class DockerProcess:
    """Small process-like handle whose lifecycle removes both container and network."""

    pid = None

    def __init__(self, runner: "DockerIsolationRunner", container_id: str, network_name: str) -> None:
        self._runner = runner
        self.container_id = container_id
        self.network_name = network_name
        self._stopped = False

    def poll(self) -> int | None:
        if self._stopped:
            return 0
        result = self._runner._docker(
            "inspect", "--format", "{{.State.Running}}", self.container_id,
            check=False,
        )
        return None if result.returncode == 0 and result.stdout.strip().lower() == "true" else 1

    def terminate(self) -> None:
        if not self._stopped:
            self._runner._docker("stop", "--time", "5", self.container_id, check=False)
            self._runner._docker("network", "rm", self.network_name, check=False)
            self._stopped = True

    def kill(self) -> None:
        if not self._stopped:
            self._runner._docker("kill", self.container_id, check=False)
            self._runner._docker("network", "rm", self.network_name, check=False)
            self._stopped = True

    def wait(self, timeout: float | None = None) -> int:
        if self._stopped:
            return 0
        arguments = ["wait"]
        if timeout is not None:
            arguments = ["--timeout", str(max(1, int(timeout))), "docker", "wait"]
            result = self._runner._run_wsl(*arguments, check=False)
        else:
            result = self._runner._docker(*arguments, self.container_id, check=False)
        if result.returncode != 0:
            raise subprocess.TimeoutExpired("docker wait", timeout)
        self._runner._docker("network", "rm", self.network_name, check=False)
        self._stopped = True
        try:
            return int(result.stdout.strip() or "0")
        except ValueError:
            return result.returncode


class DockerIsolationRunner:
    """Launches candidates in a non-privileged Docker boundary through WSL."""

    def __init__(
        self,
        *,
        distro: str = "Ubuntu",
        command_runner: Callable[..., Any] = subprocess.run,
        path_translator: Callable[[Path], str] | None = None,
    ) -> None:
        self.distro = distro
        self._command_runner = command_runner
        self._path_translator = path_translator or self._translate_path

    def _run_wsl(self, *arguments: str, check: bool = True):
        result = self._command_runner(
            ["wsl.exe", "-d", self.distro, "--", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise IsolationUnavailable(result.stderr.strip() or "restricted Docker boundary is unavailable")
        return result

    def _docker(self, *arguments: str, check: bool = True):
        return self._run_wsl("docker", *arguments, check=check)

    def _translate_path(self, path: Path) -> str:
        windows_path = str(path.resolve()).replace("\\", "/")
        result = self._run_wsl("wslpath", "-a", windows_path)
        translated = result.stdout.strip()
        if not translated.startswith("/"):
            raise IsolationUnavailable("host path could not be translated for the isolated boundary")
        return translated

    def resolve_image(self, image: str) -> str:
        if not image:
            raise IsolationUnavailable("container image is required")
        self._docker("info")
        result = self._docker("image", "inspect", "--format", "{{.Id}}", image)
        resolved = result.stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", resolved):
            raise IsolationUnavailable("container image did not resolve to an immutable image ID")
        return resolved

    def launch(
        self,
        *,
        artifact_root: str | Path,
        data_root: str | Path,
        image: str,
        command: tuple[str, ...],
        host_port: int,
        container_port: int,
        environment: Mapping[str, str],
        artifact_digest: str,
    ) -> DockerProcess:
        if not image or not command:
            raise IsolationUnavailable("container image and command are required")
        artifact = Path(artifact_root).resolve(strict=True)
        data = Path(data_root).resolve(strict=True)
        if ArtifactMaterializer._directory_digest(artifact) != artifact_digest:
            raise IsolationUnavailable("candidate artifact content changed before container launch")
        resolved_image = self.resolve_image(image)
        artifact_mount = self._path_translator(artifact)
        data_mount = self._path_translator(data)
        network_name = f"json-codr-candidate-{uuid7()}"
        self._docker(
            "network", "create", "--driver", "bridge",
            "--opt", "com.docker.network.bridge.enable_icc=false", network_name,
        )
        arguments = [
            "run", "--rm", "--detach",
            "--name", network_name,
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--user", "65534:65534",
            "--pids-limit", "256",
            "--memory", "1024m",
            "--cpus", "2",
            "--network", network_name,
            "--publish", f"127.0.0.1:{host_port}:{container_port}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--workdir", "/app",
            "-v", f"{artifact_mount}:/app:ro",
            "-v", f"{data_mount}:/data:rw",
        ]
        for key, value in sorted(environment.items()):
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                self._docker("network", "rm", network_name, check=False)
                raise IsolationUnavailable("candidate environment contains an invalid entry")
            arguments.extend(("--env", f"{key}={value}"))
        arguments.extend((resolved_image, *command))
        try:
            result = self._docker(*arguments)
        except Exception:
            self._docker("network", "rm", network_name, check=False)
            raise
        container_id = result.stdout.strip()
        if not container_id:
            self._docker("network", "rm", network_name, check=False)
            raise IsolationUnavailable("Docker did not return a candidate container identity")
        return DockerProcess(self, container_id, network_name)

    def recover(self, container_id: str, container_name: str) -> DockerProcess:
        process = DockerProcess(self, container_id, container_name)
        if process.poll() is not None:
            raise IsolationUnavailable("candidate health container is no longer running")
        return process

    def discard(self, container_id: str, container_name: str) -> None:
        self._docker("stop", "--time", "5", container_id, check=False)
        self._docker("network", "rm", container_name, check=False)


class PlaywrightBrowserProbe:
    """Loads the real page and rejects browser console/page failures."""

    def __init__(self, *, timeout_ms: int = 10_000) -> None:
        self.timeout_ms = timeout_ms

    def __call__(self, base_url: str) -> Mapping[str, Any]:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        deadline = time.monotonic() + (self.timeout_ms / 1000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                while True:
                    fatal_errors: list[str] = []
                    page = browser.new_page()
                    page.on(
                        "console",
                        lambda message: fatal_errors.append(f"console: {message.text}")
                        if message.type == "error" else None,
                    )
                    page.on("pageerror", lambda error: fatal_errors.append(f"page: {error}"))
                    try:
                        remaining_ms = max(250, int((deadline - time.monotonic()) * 1000))
                        response = page.goto(
                            base_url, wait_until="load", timeout=remaining_ms
                        )
                        page.wait_for_timeout(100)
                        loaded = response is not None and response.ok
                        break
                    except PlaywrightError as error:
                        page.close()
                        if time.monotonic() >= deadline:
                            return {
                                "loaded": False,
                                "fatal_errors": (f"navigation: {error}",),
                            }
                        time.sleep(0.1)
            finally:
                browser.close()
        return {"loaded": loaded, "fatal_errors": tuple(fatal_errors)}


def _sync_parent(path: Path) -> None:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW(
            str(path), 0x40000000, 0x00000007, None, 3, 0x02000000, None
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(kernel32.GetLastError())
        try:
            if not kernel32.FlushFileBuffers(handle):
                raise ctypes.WinError(kernel32.GetLastError())
        finally:
            kernel32.CloseHandle(handle)
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_bytes(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        _sync_parent(target.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_or_create_supervisor_key(path: str | Path) -> bytes:
    target = Path(path).resolve()
    if target.is_file():
        value = target.read_bytes()
        if len(value) != 32:
            raise RuntimeError("supervisor signing key is invalid")
        return value
    target.parent.mkdir(parents=True, exist_ok=True)
    value = os.urandom(32)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_or_create_supervisor_key(target)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_parent(target.parent)
    return value


class HealthReceiptSigner:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("health receipt signing key must contain at least 32 bytes")
        self._key = bytes(key)

    @staticmethod
    def _material(receipt: "HealthReceipt") -> dict[str, Any]:
        return receipt.model_dump(mode="json", exclude={"signature"})

    def sign(self, receipt: "HealthReceipt") -> "HealthReceipt":
        signature = "hmac-sha256:" + hmac.new(
            self._key, canonical_json(self._material(receipt)), hashlib.sha256
        ).hexdigest()
        return receipt.model_copy(update={"signature": signature})

    def validate(self, receipt: "HealthReceipt") -> bool:
        expected = "hmac-sha256:" + hmac.new(
            self._key, canonical_json(self._material(receipt)), hashlib.sha256
        ).hexdigest()
        return bool(receipt.signature) and hmac.compare_digest(receipt.signature, expected)


class SupervisorRequestError(RuntimeError):
    def __init__(self, message: str, rollback_receipt: Mapping[str, Any] | None = None) -> None:
        self.rollback_receipt = rollback_receipt
        super().__init__(message)


class FileSupervisorClient:
    """Authenticated, durable file IPC to the separately running stable supervisor."""

    def __init__(
        self,
        root: str | Path,
        *,
        key: bytes,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        self.requests.mkdir(parents=True, exist_ok=True)
        self.responses.mkdir(parents=True, exist_ok=True)
        self.pointer_path = self.root.parent / "pointer" / "active-build.json"
        self._key = bytes(key)
        self._timeout = timeout_seconds

    def load(self) -> Mapping[str, Any] | None:
        if not self.pointer_path.is_file():
            return None
        value = json.loads(self.pointer_path.read_text(encoding="utf-8"))
        return value if isinstance(value, Mapping) else None

    def _signature(self, value: Mapping[str, Any]) -> str:
        material = {key: item for key, item in value.items() if key != "signature"}
        return "hmac-sha256:" + hmac.new(
            self._key, canonical_json(material), hashlib.sha256
        ).hexdigest()

    def _submit(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = f"request-{uuid7()}"
        request = {
            "request_id": request_id,
            "operation": operation,
            "payload": dict(payload),
            "issued_at": datetime.now(UTC).isoformat(),
        }
        request["signature"] = self._signature(request)
        _atomic_bytes(
            self.requests / f"{request_id}.json",
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        response_path = self.responses / f"{request_id}.json"
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if response_path.is_file():
                response = json.loads(response_path.read_text(encoding="utf-8"))
                response_path.unlink(missing_ok=True)
                if not isinstance(response, dict) or not hmac.compare_digest(
                    str(response.get("signature", "")), self._signature(response)
                ):
                    raise SupervisorRequestError("supervisor response signature is invalid")
                if response.get("ok") is not True:
                    raise SupervisorRequestError(
                        str(response.get("error") or "stable supervisor rejected the request"),
                        response.get("rollback_receipt"),
                    )
                result = response.get("result")
                if not isinstance(result, Mapping):
                    raise SupervisorRequestError("stable supervisor returned an invalid result")
                return dict(result)
            time.sleep(0.05)
        raise SupervisorRequestError("stable supervisor did not answer before the deadline")

    def activate(self, health: "HealthReceipt", target_pointer: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._submit("activate", {
            "activation_id": f"activation-{health.candidate_id}",
            "health_receipt": health.model_dump(mode="json"),
            "target_pointer": dict(target_pointer),
        })

    def rollback(self, activation_id: str) -> Mapping[str, Any]:
        return self._submit("rollback", {"activation_id": activation_id})

    def reconcile_activation(self, candidate_id: str) -> Mapping[str, Any] | None:
        identifier = f"activation-{candidate_id}"
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in identifier):
            return None
        path = self.root.parent / "pointer" / "activations" / f"{identifier}.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, Mapping) else None

    def reconcile_rollback(self, activation_id: str) -> Mapping[str, Any] | None:
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in activation_id):
            return None
        path = self.root.parent / "pointer" / "rollbacks" / f"{activation_id}.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, Mapping) else None


class HealthReceipt(FrozenContract):
    health_id: str
    candidate_id: str
    revision: str | None
    tree_sha: str | None = None
    root: str
    version: str | None
    update_profile_digest: str | None = None
    verification_profile_digest: str | None = None
    manifest_digest: str | None = None
    manifest_signature: str | None = None
    artifact_digest: str | None = None
    signature: str | None = None
    container_id: str | None = None
    container_name: str | None = None
    container_image: str | None = None
    launch_argv: tuple[str, ...] = ()
    container_port: int = Field(default=8000, ge=1, le=65535)
    health_nonce: str | None = None
    instance_id: str | None = None
    started_at: datetime | None = None
    fresh_until: datetime | None = None
    isolation: Literal["docker-restricted", "unknown"] = "unknown"
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=0, le=65535)
    data_root: str
    pid: int | None
    healthy: bool
    checks: tuple[str, ...] = ()
    browser_fatal_errors: tuple[str, ...] = ()
    error: str | None = None
    migration_compatibility: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CandidateHealthError(RuntimeError):
    def __init__(self, receipt: HealthReceipt) -> None:
        self.receipt = receipt
        super().__init__(receipt.error or "candidate health check failed")


class ActivationError(RuntimeError):
    def __init__(self, message: str, rollback_receipt: Mapping[str, Any]) -> None:
        self.rollback_receipt = rollback_receipt
        super().__init__(message)


class UpdateLauncher:
    def __init__(
        self,
        state_root: str | Path,
        *,
        materializer: ArtifactMaterializer | None = None,
        isolation_runner: DockerIsolationRunner | None = None,
        manifest_signer: BuildManifestSigner | None = None,
        health_signer: HealthReceiptSigner | None = None,
        supervisor_client: object | None = None,
        http_probe: Callable[..., Mapping[str, Any]] | None = None,
        browser_probe: Callable[[str], Mapping[str, Any]] | None = None,
        port_allocator: Callable[[], int] | None = None,
        port_available: Callable[[int], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        key = load_or_create_supervisor_key(
            self.state_root / "security" / "supervisor.key"
        )
        self._materializer = materializer or ArtifactMaterializer(self.state_root / "artifacts")
        self._isolation_runner = isolation_runner or DockerIsolationRunner()
        self._manifest_signer = manifest_signer or BuildManifestSigner(key=key)
        self._health_signer = health_signer or HealthReceiptSigner(key)
        self._supervisor = supervisor_client or FileSupervisorClient(
            self.state_root / "control", key=key
        )
        self.pointer_store = self._supervisor if hasattr(self._supervisor, "load") else None
        self._http_probe = http_probe or self._default_http_probe
        self._browser_probe = browser_probe or PlaywrightBrowserProbe()
        self._port_allocator = port_allocator or self._allocate_port
        self._port_available = port_available or self._is_port_available
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self._processes: dict[str, Any] = {}

    def launch_candidate(self, candidate, profile) -> HealthReceipt:
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        revision = getattr(candidate, "commit_sha", None)
        version = getattr(profile, "expected_version", None)
        migration = str(getattr(profile, "migration_compatibility", ""))
        health_id = f"health-{uuid7()}"
        data_root = self.state_root / "candidate-data" / health_id
        port = 0
        process = None
        artifact: MaterializedBuild | None = None
        signed_manifest: BuildManifest | None = None
        checks: list[str] = []
        browser_errors: tuple[str, ...] = ()

        def failure(message: str) -> CandidateHealthError:
            if process is not None:
                self._terminate(process)
                self._processes.pop(health_id, None)
            receipt = HealthReceipt(
                health_id=health_id,
                candidate_id=candidate_id or "unknown-candidate",
                revision=revision,
                tree_sha=None if artifact is None else artifact.tree_sha,
                root="" if artifact is None else artifact.root,
                version=version,
                update_profile_digest=None if artifact is None else artifact.update_profile_digest,
                verification_profile_digest=None if artifact is None else artifact.verification_profile_digest,
                manifest_digest=None if signed_manifest is None else signed_manifest.manifest_digest,
                manifest_signature=None if signed_manifest is None else signed_manifest.signature,
                artifact_digest=None if artifact is None else artifact.artifact_digest,
                port=port,
                data_root=str(data_root),
                pid=None if process is None else getattr(process, "pid", None),
                container_id=None if process is None else getattr(process, "container_id", None),
                container_name=None if process is None else getattr(process, "network_name", None),
                healthy=False,
                checks=tuple(checks),
                browser_fatal_errors=browser_errors,
                error=message,
                migration_compatibility=migration or "unknown",
            )
            return CandidateHealthError(self._health_signer.sign(receipt))

        if migration != "backward_compatible":
            raise failure("candidate migration is not backward compatible")
        if not candidate_id or not revision:
            raise failure("candidate launch identity is invalid")
        if not version:
            raise failure("candidate expected version is not configured")
        image = str(getattr(profile, "container_image", "") or "")
        if not image:
            raise failure("candidate restricted container image is not configured")
        launch_argv = tuple(getattr(profile, "launch_argv", ()))
        if not launch_argv:
            raise failure("candidate launch profile has no server-owned command")
        try:
            artifact = self._materializer.materialize(candidate, profile)
            checks.append("immutable-artifact")
            resolve_image = getattr(self._isolation_runner, "resolve_image", None)
            if not callable(resolve_image):
                raise IsolationUnavailable("restricted runner cannot resolve immutable images")
            image = str(resolve_image(image))
            container_port = int(getattr(profile, "container_port", 8000))
            arguments = tuple(
                argument.format(host="0.0.0.0", port=container_port)
                for argument in launch_argv
            )
            signed_manifest = self._manifest_signer.sign(BuildManifest(
                candidate_id=candidate_id,
                revision=artifact.revision,
                tree_sha=artifact.tree_sha,
                update_profile_digest=artifact.update_profile_digest,
                verification_profile_digest=artifact.verification_profile_digest,
                version=artifact.version,
                migration_compatibility=migration,
                artifact_root=artifact.root,
                artifact_digest=artifact.artifact_digest,
                container_image=image,
                launch_argv=arguments,
                container_port=container_port,
            ))
            manifests_root = self.state_root / "manifests"
            _atomic_bytes(
                manifests_root / f"{health_id}.json",
                signed_manifest.model_dump_json(indent=2).encode("utf-8"),
            )
            checks.append("signed-manifest")
            port = self._port_allocator()
            if not self._port_available(port):
                raise failure(f"candidate loopback port {port} is unavailable")
            data_root.mkdir(parents=True, exist_ok=False)
            instance_id = f"instance-{uuid7()}"
            started_at = self._now()
            nonce = os.urandom(24).hex()
            environment = {
                "JSON_CODR_REVISION": revision,
                "JSON_CODR_EXPECTED_VERSION": version,
                "JSON_CODR_DATA_ROOT": "/data",
                "JSON_CODR_HOST": "0.0.0.0",
                "JSON_CODR_PORT": str(container_port),
                "JSON_CODR_ARTIFACT_MANIFEST": str(signed_manifest.manifest_digest),
                "JSON_CODR_INSTANCE_ID": instance_id,
                "JSON_CODR_STARTED_AT": started_at.isoformat(),
                "OLLAMA_NO_CLOUD": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
            process = self._isolation_runner.launch(
                artifact_root=artifact.root,
                data_root=data_root,
                image=image,
                command=arguments,
                host_port=port,
                container_port=container_port,
                environment=environment,
                artifact_digest=artifact.artifact_digest,
            )
            self._processes[health_id] = process
            if process.poll() is not None:
                raise failure(f"candidate process exited with code {process.poll()}")
            checks.extend(("restricted-container", "startup"))
            base_url = f"http://127.0.0.1:{port}"
            deadline = self._monotonic() + float(getattr(profile, "startup_timeout_seconds", 30))
            while True:
                try:
                    health = dict(self._call_http(
                        f"{base_url}/api/health", 2.0,
                        {"X-JSON-CODR-Health-Nonce": nonce},
                    ))
                    break
                except (OSError, TimeoutError) as error:
                    if process.poll() is not None:
                        raise failure(f"candidate process exited with code {process.poll()}") from error
                    if self._monotonic() >= deadline:
                        raise failure("candidate API did not become ready before the deadline") from error
                    self._sleep(0.1)
            if health.get("status") != "ready":
                raise failure("candidate API health response is not ready")
            if health.get("revision") != revision:
                raise failure("candidate API reported the wrong revision")
            if health.get("app_version") != version:
                raise failure("candidate API reported a version mismatch")
            if health.get("health_nonce") != nonce:
                raise failure("candidate API did not prove fresh health liveness")
            if health.get("instance_id") != instance_id:
                raise failure("candidate API reported the wrong process instance")
            if health.get("started_at") != started_at.isoformat():
                raise failure("candidate API reported the wrong process start identity")
            if health.get("manifest_digest") != signed_manifest.manifest_digest:
                raise failure("candidate API reported the wrong build manifest")
            checks.extend(("api", "fresh-liveness"))
            while True:
                try:
                    openapi = dict(self._call_http(f"{base_url}/openapi.json", 2.0, {}))
                    break
                except (OSError, TimeoutError) as error:
                    if process.poll() is not None:
                        raise failure(f"candidate process exited with code {process.poll()}") from error
                    if self._monotonic() >= deadline:
                        raise failure(
                            "candidate OpenAPI document did not become ready before the deadline"
                        ) from error
                    self._sleep(0.1)
            if not isinstance(openapi.get("openapi"), str):
                raise failure("candidate API did not return an OpenAPI document")
            checks.append("openapi")
            browser = dict(self._browser_probe(base_url))
            browser_errors = tuple(str(item) for item in browser.get("fatal_errors", ()))
            if browser.get("loaded") is not True or browser_errors:
                raise failure("candidate browser health reported fatal errors")
            checks.append("browser")
        except CandidateHealthError:
            raise
        except Exception as error:
            raise failure(f"candidate startup or API failure: {error}") from error
        checked_at = self._now()
        receipt = HealthReceipt(
            health_id=health_id,
            candidate_id=candidate_id,
            revision=revision,
            tree_sha=artifact.tree_sha,
            root=artifact.root,
            version=version,
            update_profile_digest=artifact.update_profile_digest,
            verification_profile_digest=artifact.verification_profile_digest,
            manifest_digest=signed_manifest.manifest_digest,
            manifest_signature=signed_manifest.signature,
            artifact_digest=artifact.artifact_digest,
            port=port,
            data_root=str(data_root),
            pid=getattr(process, "pid", None),
            container_id=getattr(process, "container_id", None),
            container_name=getattr(process, "network_name", None),
            container_image=image,
            launch_argv=arguments,
            container_port=container_port,
            health_nonce=nonce,
            instance_id=instance_id,
            started_at=started_at,
            fresh_until=checked_at + timedelta(seconds=30),
            isolation="docker-restricted",
            healthy=True,
            checks=tuple(checks),
            browser_fatal_errors=(),
            migration_compatibility=migration,
            checked_at=checked_at,
        )
        signed_receipt = self._health_signer.sign(receipt)
        receipts_root = self.state_root / "health-receipts"
        _atomic_bytes(
            receipts_root / f"{candidate_id}.json",
            signed_receipt.model_dump_json(indent=2).encode("utf-8"),
        )
        return signed_receipt

    def reconcile_health(self, candidate) -> HealthReceipt | None:
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        if not candidate_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in candidate_id):
            return None
        path = self.state_root / "health-receipts" / f"{candidate_id}.json"
        if not path.is_file():
            return None
        receipt = HealthReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        if not self._health_signer.validate(receipt):
            return None
        if (
            receipt.revision != getattr(candidate, "commit_sha", None)
            or receipt.fresh_until is None
            or receipt.fresh_until <= self._now()
            or not receipt.container_id
            or not receipt.container_name
        ):
            self._discard_reconciled_health(receipt)
            return None
        process = self._processes.get(receipt.health_id)
        if process is None:
            recover = getattr(self._isolation_runner, "recover", None)
            if not callable(recover):
                return None
            try:
                process = recover(receipt.container_id, receipt.container_name)
            except Exception:
                return None
            self._processes[receipt.health_id] = process
        if process.poll() is not None:
            return None
        nonce = os.urandom(24).hex()
        observed = dict(self._call_http(
            f"http://{receipt.host}:{receipt.port}/api/health", 2.0,
            {"X-JSON-CODR-Health-Nonce": nonce},
        ))
        if (
            observed.get("revision") != receipt.revision
            or observed.get("health_nonce") != nonce
            or observed.get("instance_id") != receipt.instance_id
            or observed.get("manifest_digest") != receipt.manifest_digest
        ):
            return None
        return receipt

    def _discard_reconciled_health(self, receipt: HealthReceipt) -> None:
        process = self._processes.pop(receipt.health_id, None)
        if process is None and receipt.container_id and receipt.container_name:
            recover = getattr(self._isolation_runner, "recover", None)
            if callable(recover):
                try:
                    process = recover(receipt.container_id, receipt.container_name)
                except Exception:
                    process = None
                    discard = getattr(self._isolation_runner, "discard", None)
                    if callable(discard):
                        discard(receipt.container_id, receipt.container_name)
        if process is not None:
            self._terminate(process)

    def activate(self, receipt: HealthReceipt | Mapping[str, Any]):
        health = receipt if isinstance(receipt, HealthReceipt) else HealthReceipt.model_validate(receipt)
        if not health.healthy or not health.revision or not health.version or not health.tree_sha:
            raise PermissionError("activation requires a healthy typed receipt")
        if not self._health_signer.validate(health):
            raise PermissionError("activation health receipt signature is invalid")
        if health.migration_compatibility != "backward_compatible":
            raise PermissionError("activation requires a backward-compatible migration")
        now = self._now()
        if health.fresh_until is None or health.fresh_until <= now:
            raise PermissionError("activation health receipt is stale")
        process = self._processes.get(health.health_id)
        if process is None or process.poll() is not None:
            raise PermissionError("activation candidate is no longer live")
        nonce = os.urandom(24).hex()
        deadline = self._monotonic() + 5.0
        while True:
            try:
                observed = dict(self._call_http(
                    f"http://{health.host}:{health.port}/api/health", 2.0,
                    {"X-JSON-CODR-Health-Nonce": nonce},
                ))
                break
            except (OSError, TimeoutError) as error:
                if process.poll() is not None or self._monotonic() >= deadline:
                    raise PermissionError(
                        "candidate failed the immediate activation liveness re-probe"
                    ) from error
                self._sleep(0.1)
        if (
            observed.get("status") != "ready"
            or observed.get("revision") != health.revision
            or observed.get("app_version") != health.version
            or observed.get("health_nonce") != nonce
            or observed.get("instance_id") != health.instance_id
            or observed.get("manifest_digest") != health.manifest_digest
        ):
            raise PermissionError("candidate failed the immediate activation re-probe")
        browser = dict(self._browser_probe(f"http://{health.host}:{health.port}"))
        if browser.get("loaded") is not True or tuple(browser.get("fatal_errors", ())):
            raise PermissionError("candidate failed the immediate activation browser re-probe")
        target = {
            "revision": health.revision,
            "tree_sha": health.tree_sha,
            "root": str(Path(health.root).resolve(strict=True)),
            "version": health.version,
            "runner": "docker",
            "launch_argv": list(health.launch_argv),
            "manifest_digest": health.manifest_digest,
            "manifest_signature": health.manifest_signature,
            "artifact_digest": health.artifact_digest,
            "container_image": health.container_image,
            "container_port": health.container_port,
            "data_root": health.data_root,
            "health_signature": health.signature,
        }
        try:
            activation = self._supervisor.activate(health, target)
        except SupervisorRequestError as error:
            if error.rollback_receipt is not None:
                raise ActivationError(str(error), error.rollback_receipt) from error
            raise
        self.terminate_health(health.health_id)
        return activation

    def rollback(self, activation_id: str):
        return self._supervisor.rollback(activation_id)

    def reconcile_activation(self, candidate_id: str):
        reconcile = getattr(self._supervisor, "reconcile_activation", None)
        return None if not callable(reconcile) else reconcile(candidate_id)

    def reconcile_rollback(self, activation_id: str):
        reconcile = getattr(self._supervisor, "reconcile_rollback", None)
        return None if not callable(reconcile) else reconcile(activation_id)

    def terminate_health(self, health_id: str) -> None:
        process = self._processes.pop(health_id, None)
        if process is not None:
            self._terminate(process)

    def close(self) -> None:
        for health_id in tuple(self._processes):
            self.terminate_health(health_id)

    @staticmethod
    def _terminate(process: Any) -> None:
        running = process.poll() is None
        if running:
            process.terminate()
            try:
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, TimeoutError):
                process.kill()
                process.wait(timeout=5)
        elif isinstance(process, DockerProcess):
            process.terminate()
        for name in ("stdout", "stderr", "stdin"):
            stream = getattr(process, name, None)
            if stream is not None:
                stream.close()

    @staticmethod
    def _allocate_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
            stream.bind(("127.0.0.1", 0))
            return int(stream.getsockname()[1])

    @staticmethod
    def _is_port_available(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
                stream.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True

    def _call_http(
        self, url: str, timeout: float, headers: Mapping[str, str]
    ) -> Mapping[str, Any]:
        try:
            return self._http_probe(url, timeout, headers)
        except TypeError as error:
            try:
                return self._http_probe(url, timeout)
            except TypeError:
                raise error

    @staticmethod
    def _default_http_probe(
        url: str, timeout: float, headers: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        from urllib.request import Request

        with urlopen(Request(url, headers=dict(headers or {})), timeout=timeout) as response:
            if response.status != 200:
                raise OSError(f"HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
