"""Stable, stdlib-only JSON_CODR build supervisor.

This module is intentionally independent of candidate application imports.  It owns
the active pointer, activation journal, public child, and rollback decision.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_id(value: str) -> str:
    if not value or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in value
    ):
        raise ValueError("supervisor receipt id is invalid")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _signature(key: bytes, value: dict[str, Any]) -> str:
    material = {name: item for name, item in value.items() if name != "signature"}
    return "hmac-sha256:" + hmac.new(
        key, _canonical_json(material), hashlib.sha256
    ).hexdigest()


def _artifact_digest(root: Path) -> str:
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


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_supervisor_key(path: Path) -> bytes:
    try:
        value = path.read_bytes()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = os.urandom(32)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return _load_supervisor_key(path)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(path.parent)
    if len(value) != 32:
        raise RuntimeError("stable supervisor signing key is invalid")
    return value


def _sync_directory(path: Path) -> None:
    """Flush directory metadata after an atomic replace.

    Windows requires a directory handle opened with backup semantics.  Unsupported
    filesystems fail closed because durable pointer state is a release prerequisite.
    """
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path),
        0x40000000,  # GENERIC_WRITE is required by FlushFileBuffers
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise ctypes.WinError()
    try:
        if not kernel32.FlushFileBuffers(handle):
            error = kernel32.GetLastError()
            raise ctypes.WinError(error)
    finally:
        kernel32.CloseHandle(handle)


@contextlib.contextmanager
def _file_lock(path: Path, timeout: float = 10.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        deadline = time.monotonic() + timeout
        while not locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise RuntimeError("supervisor activation lock is busy") from error
                time.sleep(0.05)
        yield
    finally:
        if locked:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class PointerStore:
    """Crash-durable pointer, journal, and supervisor receipts."""

    def __init__(
        self,
        pointer_path: str | Path,
        *,
        directory_sync: Callable[[Path], None] = _sync_directory,
        replacer: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
    ) -> None:
        self.pointer_path = Path(pointer_path).resolve()
        self.root = self.pointer_path.parent
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.root / "activation-journal.json"
        self.lock_path = self.root / "activation.lock"
        self.activations_root = self.root / "activations"
        self.rollbacks_root = self.root / "rollbacks"
        self.activations_root.mkdir(exist_ok=True)
        self.rollbacks_root.mkdir(exist_ok=True)
        self._directory_sync = directory_sync
        self._replace = replacer

    def load(self) -> dict[str, Any] | None:
        if not self.pointer_path.is_file():
            return None
        payload = json.loads(self.pointer_path.read_text(encoding="utf-8"))
        self._validate_pointer(payload)
        return payload

    def ensure_known_good(self, fallback: dict[str, Any]) -> dict[str, Any]:
        with _file_lock(self.lock_path):
            existing = self.load()
            if existing is not None:
                return existing
            pointer = dict(fallback)
            pointer["schema_version"] = 1
            pointer["generation"] = 0
            pointer["known_good"] = True
            pointer.setdefault("activated_at", _utc_now())
            pointer.setdefault("previous_revision", None)
            self._validate_pointer(pointer)
            self._atomic_write(self.pointer_path, pointer)
            return pointer

    def set_missing_defaults(self, defaults: dict[str, Any]) -> dict[str, Any]:
        with _file_lock(self.lock_path):
            pointer = self.load()
            if pointer is None:
                raise RuntimeError("active build pointer is missing")
            updated = dict(pointer)
            changed = False
            for name, value in defaults.items():
                if name not in updated or updated[name] in (None, ""):
                    updated[name] = value
                    changed = True
            if changed:
                self._validate_pointer(updated)
                self._atomic_write(self.pointer_path, updated)
            return updated

    def refresh_mutable_fallback(self, fallback: dict[str, Any]) -> dict[str, Any]:
        with _file_lock(self.lock_path):
            pointer = self.load()
            if pointer is None:
                raise RuntimeError("active build pointer is missing")
            is_mutable_fallback = (
                pointer.get("runner") == "local"
                and pointer.get("generation") == 0
                and pointer.get("previous_revision") is None
                and pointer.get("manifest_digest") == f"fallback:{pointer.get('revision')}"
                and Path(str(pointer.get("root", ""))).resolve()
                == Path(str(fallback["root"])).resolve()
            )
            if not is_mutable_fallback or pointer.get("revision") == fallback.get("revision"):
                return pointer
            updated = dict(fallback)
            updated["schema_version"] = 1
            updated["generation"] = 0
            updated["known_good"] = True
            updated.setdefault("activated_at", _utc_now())
            updated.setdefault("previous_revision", None)
            self._validate_pointer(updated)
            self._atomic_write(self.pointer_path, updated)
            return updated

    def compare_and_swap(
        self, expected_generation: int, target: dict[str, Any]
    ) -> dict[str, Any]:
        with _file_lock(self.lock_path):
            return self.compare_and_swap_locked(expected_generation, target)

    def compare_and_swap_locked(
        self, expected_generation: int, target: dict[str, Any]
    ) -> dict[str, Any]:
        """CAS while the caller already owns ``lock_path``."""
        current = self.load()
        if current is None:
            raise RuntimeError("active build pointer is missing")
        if int(current["generation"]) != expected_generation:
            raise RuntimeError(
                f"active build generation changed from {expected_generation} "
                f"to {current['generation']}"
            )
        updated = dict(target)
        updated["schema_version"] = 1
        updated["generation"] = expected_generation + 1
        updated["known_good"] = bool(updated.get("known_good", True))
        updated["previous_revision"] = current["revision"]
        updated.setdefault("activated_at", _utc_now())
        self._validate_pointer(updated)
        self._atomic_write(self.pointer_path, updated)
        return updated

    def write_journal(self, journal: dict[str, Any]) -> None:
        self._atomic_write(self.journal_path, journal)

    def load_journal(self) -> dict[str, Any] | None:
        if not self.journal_path.is_file():
            return None
        value = json.loads(self.journal_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("activation journal is invalid")
        return value

    def clear_journal(self) -> None:
        if self.journal_path.exists():
            self.journal_path.unlink()
            self._directory_sync(self.root)

    def save_activation(self, receipt: dict[str, Any]) -> None:
        identifier = _safe_id(str(receipt["activation_id"]))
        self._atomic_write(self.activations_root / f"{identifier}.json", receipt)

    def activation(self, activation_id: str) -> dict[str, Any]:
        path = self.activations_root / f"{_safe_id(activation_id)}.json"
        if not path.is_file():
            raise KeyError(activation_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def save_rollback(self, receipt: dict[str, Any]) -> None:
        identifier = _safe_id(str(receipt["activation_id"]))
        self._atomic_write(self.rollbacks_root / f"{identifier}.json", receipt)

    def rollback(self, activation_id: str) -> dict[str, Any] | None:
        path = self.rollbacks_root / f"{_safe_id(activation_id)}.json"
        return None if not path.is_file() else json.loads(path.read_text(encoding="utf-8"))

    def _atomic_write(self, target: Path, payload: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            self._replace(temporary, target)
            self._directory_sync(target.parent)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_pointer(pointer: dict[str, Any]) -> None:
        required = {
            "revision", "tree_sha", "root", "version", "runner",
            "launch_argv", "manifest_digest", "generation",
        }
        if not isinstance(pointer, dict) or required - set(pointer):
            raise ValueError("active build pointer is incomplete")
        if not isinstance(pointer["generation"], int) or pointer["generation"] < 0:
            raise ValueError("active build pointer generation is invalid")
        if not isinstance(pointer["launch_argv"], list) or not pointer["launch_argv"]:
            raise ValueError("active build launch command is invalid")


class ActivationSwitchError(RuntimeError):
    def __init__(self, message: str, rollback_receipt: dict[str, Any]) -> None:
        self.rollback_receipt = rollback_receipt
        super().__init__(message)


class StableSupervisor:
    """Own the public child and every pointer transition."""

    def __init__(
        self,
        store: PointerStore,
        *,
        runner: Any,
        probe: Callable[[str, int, str], bool],
        host: str,
        port: int,
        receipt_validator: Callable[[dict[str, Any]], bool],
    ) -> None:
        self.store = store
        self.runner = runner
        self.probe = probe
        self.host = host
        self.port = port
        self.receipt_validator = receipt_validator
        self._child = None

    def initialize(self, fallback: dict[str, Any]) -> dict[str, Any]:
        self.store.ensure_known_good(fallback)
        self._recover_incomplete()
        active = self.store.load()
        if active is None:
            raise RuntimeError("active build pointer is missing")
        if self._child is not None:
            self.runner.stop(self._child)
        self._child = self._start_checked(active)
        return active

    def activate(self, request: dict[str, Any]) -> dict[str, Any]:
        health = request.get("health_receipt")
        if not isinstance(health, dict) or not self.receipt_validator(health):
            raise PermissionError("activation requires a supervisor-verifiable health receipt")
        activation_id = _safe_id(str(request.get("activation_id", "")))
        expected_generation = int(request.get("expected_generation", -1))
        target = dict(request.get("target_pointer") or {})
        bindings = {
            "revision": "revision",
            "tree_sha": "tree_sha",
            "root": "root",
            "version": "version",
            "manifest_digest": "manifest_digest",
            "manifest_signature": "manifest_signature",
            "artifact_digest": "artifact_digest",
            "container_image": "container_image",
            "container_port": "container_port",
        }
        for target_name, health_name in bindings.items():
            if target.get(target_name) != health.get(health_name):
                raise PermissionError(
                    f"health receipt is not bound to target field {target_name}"
                )
        if target.get("runner") != "docker":
            raise PermissionError("updated public builds require the Docker isolation runner")
        with _file_lock(self.store.lock_path):
            previous = self.store.load()
            if previous is None:
                raise RuntimeError("active build pointer is missing")
            if previous["generation"] != expected_generation:
                raise RuntimeError("active build generation changed before activation")
            journal = {
                "operation": "activate",
                "phase": "prepared",
                "activation_id": activation_id,
                "previous_pointer": previous,
                "target_pointer": target,
                "created_at": _utc_now(),
            }
            self.store.write_journal(journal)
            previous_child = self._child
            if previous_child is not None:
                self.runner.stop(previous_child)
            target_child = None
            try:
                target_child = self._start_checked(target)
                journal["phase"] = "target_healthy"
                self.store.write_journal(journal)
                active = self.store.compare_and_swap_locked(expected_generation, target)
                journal["phase"] = "pointer_committed"
                self.store.write_journal(journal)
                receipt = {
                    "activation_id": activation_id,
                    "health_id": health.get("health_id"),
                    "revision": active["revision"],
                    "previous_revision": previous["revision"],
                    "active_pointer": active,
                    "previous_pointer": previous,
                    "status": "activated",
                    "activated_at": _utc_now(),
                }
                self.store.save_activation(receipt)
                self.store.clear_journal()
                self._child = target_child
                return receipt
            except Exception as error:
                if target_child is not None:
                    self.runner.stop(target_child)
                restored_child = self._start_checked(previous)
                current = self.store.load()
                if current is not None and current["revision"] != previous["revision"]:
                    previous = self.store.compare_and_swap_locked(
                        current["generation"], previous
                    )
                rollback = {
                    "rollback_id": f"rollback-{activation_id}",
                    "activation_id": activation_id,
                    "failed_revision": target.get("revision"),
                    "restored_revision": previous["revision"],
                    "restored_pointer": previous,
                    "status": "rolled_back",
                    "reason": "immediate public health probe failed",
                    "rolled_back_at": _utc_now(),
                }
                self.store.save_rollback(rollback)
                self.store.clear_journal()
                self._child = restored_child
                raise ActivationSwitchError(
                    "post-switch health failed; previous child was restored", rollback
                ) from error

    def rollback(self, activation_id: str) -> dict[str, Any]:
        existing = self.store.rollback(activation_id)
        if existing is not None:
            return existing
        activation = self.store.activation(activation_id)
        previous = dict(activation["previous_pointer"])
        with _file_lock(self.store.lock_path):
            current = self.store.load()
            if current is None or current["revision"] != activation["revision"]:
                raise PermissionError("active build changed after this activation")
            self.store.write_journal({
                "operation": "rollback",
                "phase": "prepared",
                "activation_id": activation_id,
                "previous_pointer": previous,
                "target_pointer": current,
                "created_at": _utc_now(),
            })
            if self._child is not None:
                self.runner.stop(self._child)
            try:
                restored_child = self._start_checked(previous)
                restored = self.store.compare_and_swap_locked(
                    current["generation"], previous
                )
            except Exception:
                self._child = self._start_checked(current)
                self.store.clear_journal()
                raise
            receipt = {
                "rollback_id": f"rollback-{activation_id}",
                "activation_id": activation_id,
                "failed_revision": current["revision"],
                "restored_revision": restored["revision"],
                "restored_pointer": restored,
                "status": "rolled_back",
                "rolled_back_at": _utc_now(),
            }
            self.store.save_rollback(receipt)
            self.store.clear_journal()
            self._child = restored_child
            return receipt

    def shutdown(self) -> None:
        if self._child is not None:
            self.runner.stop(self._child)
            self._child = None

    def _recover_incomplete(self) -> None:
        journal = self.store.load_journal()
        if journal is None:
            return
        previous = dict(journal.get("previous_pointer") or {})
        current = self.store.load()
        if current is None:
            raise RuntimeError("cannot recover activation without an active pointer")
        if current["revision"] != previous.get("revision"):
            self.store.compare_and_swap(current["generation"], previous)
        self.store.clear_journal()

    def _start_checked(self, pointer: dict[str, Any]):
        child = self.runner.start(pointer, self.host, self.port)
        if not self.probe(self.host, self.port, str(pointer["revision"])):
            self.runner.stop(child)
            raise RuntimeError("public child failed its immediate health probe")
        return child


class LocalProcessRunner:
    def start(self, pointer: dict[str, Any], host: str, port: int):
        command = [
            item.format(host=host, port=port) for item in pointer["launch_argv"]
        ]
        identity = uuid4().hex
        environment = {
            **os.environ,
            "JSON_CODR_REVISION": pointer["revision"],
            "JSON_CODR_EXPECTED_VERSION": pointer["version"],
            "JSON_CODR_DATA_ROOT": pointer.get("data_root", ""),
            "JSON_CODR_ARTIFACT_MANIFEST": pointer["manifest_digest"],
            "JSON_CODR_INSTANCE_ID": f"active-{identity}",
            "JSON_CODR_STARTED_AT": _utc_now(),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.Popen(
            command,
            cwd=pointer["root"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def stop(child) -> None:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


class DockerChild:
    def __init__(self, runner: "DockerPublicRunner", container_id: str, network: str) -> None:
        self.runner = runner
        self.container_id = container_id
        self.network = network
        self.stopped = False

    def poll(self):
        if self.stopped:
            return 0
        result = self.runner._docker(
            "inspect", "--format", "{{.State.Running}}", self.container_id,
            check=False,
        )
        return None if result.returncode == 0 and result.stdout.strip().lower() == "true" else 1


class DockerPublicRunner:
    """Restricted active-build runner, independent of candidate application code."""

    def __init__(self, *, distro: str = "Ubuntu", command_runner=subprocess.run) -> None:
        self.distro = distro
        self.command_runner = command_runner

    def _wsl(self, *arguments: str, check: bool = True):
        result = self.command_runner(
            ["wsl.exe", "-d", self.distro, "--", *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or "Docker isolation is unavailable")
        return result

    def _docker(self, *arguments: str, check: bool = True):
        return self._wsl("docker", *arguments, check=check)

    def _path(self, value: str) -> str:
        windows_path = str(Path(value).resolve(strict=True)).replace("\\", "/")
        result = self._wsl("wslpath", "-a", windows_path)
        translated = result.stdout.strip()
        if not translated.startswith("/"):
            raise RuntimeError("active build path cannot be translated into Docker")
        return translated

    def start(self, pointer: dict[str, Any], host: str, port: int):
        image = str(pointer.get("container_image") or "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise RuntimeError("active Docker build image is not an immutable image ID")
        self._docker("info")
        result = self._docker("image", "inspect", "--format", "{{.Id}}", image)
        if result.stdout.strip() != image:
            raise RuntimeError("active Docker build image identity changed")
        artifact_mount = self._path(pointer["root"])
        data_mount = self._path(pointer["data_root"])
        if _artifact_digest(Path(pointer["root"]).resolve(strict=True)) != pointer.get("artifact_digest"):
            raise RuntimeError("active build artifact content does not match its signed manifest")
        identity = uuid4().hex
        network = f"json-codr-active-{identity}"
        self._docker(
            "network", "create", "--driver", "bridge",
            "--opt", "com.docker.network.bridge.enable_icc=false", network,
        )
        environment = {
            "JSON_CODR_REVISION": str(pointer["revision"]),
            "JSON_CODR_EXPECTED_VERSION": str(pointer["version"]),
            "JSON_CODR_DATA_ROOT": "/data",
            "JSON_CODR_HOST": "0.0.0.0",
            "JSON_CODR_PORT": str(pointer["container_port"]),
            "JSON_CODR_ARTIFACT_MANIFEST": str(pointer["manifest_digest"]),
            "JSON_CODR_INSTANCE_ID": f"active-{identity}",
            "JSON_CODR_STARTED_AT": _utc_now(),
            "OLLAMA_NO_CLOUD": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        arguments = [
            "run", "--rm", "--detach", "--name", network,
            "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--user", "65534:65534", "--pids-limit", "256",
            "--memory", "1024m", "--cpus", "2",
            "--network", network,
            "--publish", f"{host}:{port}:{pointer['container_port']}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--workdir", "/app",
            "-v", f"{artifact_mount}:/app:ro",
            "-v", f"{data_mount}:/data:rw",
        ]
        for name, value in sorted(environment.items()):
            arguments.extend(("--env", f"{name}={value}"))
        arguments.extend((image, *pointer["launch_argv"]))
        try:
            result = self._docker(*arguments)
        except Exception:
            self._docker("network", "rm", network, check=False)
            raise
        container_id = result.stdout.strip()
        if not container_id:
            self._docker("network", "rm", network, check=False)
            raise RuntimeError("Docker returned no active container identity")
        return DockerChild(self, container_id, network)

    def stop(self, child: DockerChild) -> None:
        if child.stopped:
            return
        self._docker("stop", "--time", "10", child.container_id, check=False)
        self._docker("network", "rm", child.network, check=False)
        child.stopped = True


class HybridRunner:
    def __init__(self, *, distro: str = "Ubuntu") -> None:
        self.local = LocalProcessRunner()
        self.docker = DockerPublicRunner(distro=distro)

    def start(self, pointer: dict[str, Any], host: str, port: int):
        if pointer.get("runner") == "local":
            return ("local", self.local.start(pointer, host, port))
        if pointer.get("runner") == "docker":
            return ("docker", self.docker.start(pointer, host, port))
        raise RuntimeError("active build runner is unsupported")

    def stop(self, child) -> None:
        kind, handle = child
        (self.local if kind == "local" else self.docker).stop(handle)


class SupervisorControl:
    def __init__(
        self, root: str | Path, supervisor: StableSupervisor, *, key: bytes
    ) -> None:
        self.root = Path(root).resolve()
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        self.requests.mkdir(parents=True, exist_ok=True)
        self.responses.mkdir(parents=True, exist_ok=True)
        self.supervisor = supervisor
        self.key = bytes(key)
        self.stopping = False

    def _valid(self, value: dict[str, Any]) -> bool:
        return hmac.compare_digest(
            str(value.get("signature", "")), _signature(self.key, value)
        )

    def process_once(self) -> bool:
        paths = sorted(self.requests.glob("request-*.json"))
        if not paths:
            return False
        path = paths[0]
        response: dict[str, Any]
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(request, dict) or not self._valid(request):
                raise PermissionError("supervisor request signature is invalid")
            request_id = _safe_id(str(request.get("request_id", "")))
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("supervisor request payload is invalid")
            operation = request.get("operation")
            if operation == "activate":
                current = self.supervisor.store.load()
                if current is None:
                    raise RuntimeError("active pointer is missing")
                result = self.supervisor.activate({
                    **payload, "expected_generation": current["generation"],
                })
            elif operation == "rollback":
                result = self.supervisor.rollback(str(payload.get("activation_id", "")))
            elif operation == "shutdown":
                result = {"status": "stopping"}
                self.stopping = True
            else:
                raise ValueError("supervisor operation is unsupported")
            response = {"request_id": request_id, "ok": True, "result": result}
        except Exception as error:
            request_id = path.stem
            response = {
                "request_id": request_id,
                "ok": False,
                "error": str(error)[:500],
            }
            rollback = getattr(error, "rollback_receipt", None)
            if isinstance(rollback, dict):
                response["rollback_receipt"] = rollback
        response["signature"] = _signature(self.key, response)
        _atomic_json(self.responses / f"{request_id}.json", response)
        path.unlink(missing_ok=True)
        _sync_directory(self.requests)
        return True

    def serve(self) -> None:
        while not self.stopping:
            if not self.process_once():
                time.sleep(0.05)


def send_shutdown_request(control_root: Path, key: bytes, timeout: float = 10.0) -> None:
    request_id = f"request-shutdown-{uuid4().hex}"
    request = {
        "request_id": request_id,
        "operation": "shutdown",
        "payload": {},
        "issued_at": _utc_now(),
    }
    request["signature"] = _signature(key, request)
    requests = control_root / "requests"
    responses = control_root / "responses"
    _atomic_json(requests / f"{request_id}.json", request)
    response_path = responses / f"{request_id}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if response_path.is_file():
            response = json.loads(response_path.read_text(encoding="utf-8"))
            response_path.unlink(missing_ok=True)
            if not isinstance(response, dict) or not hmac.compare_digest(
                str(response.get("signature", "")), _signature(key, response)
            ):
                raise RuntimeError("supervisor shutdown response signature is invalid")
            if response.get("ok") is not True:
                raise RuntimeError(str(response.get("error") or "supervisor rejected shutdown"))
            return
        time.sleep(0.05)
    raise TimeoutError("stable supervisor did not acknowledge shutdown")


def health_receipt_validator(key: bytes) -> Callable[[dict[str, Any]], bool]:
    def validate(receipt: dict[str, Any]) -> bool:
        if not isinstance(receipt, dict):
            return False
        signature = str(receipt.get("signature", ""))
        if not hmac.compare_digest(signature, _signature(key, receipt)):
            return False
        try:
            fresh_until = datetime.fromisoformat(str(receipt["fresh_until"]))
        except (KeyError, ValueError):
            return False
        return (
            receipt.get("healthy") is True
            and receipt.get("isolation") == "docker-restricted"
            and fresh_until > datetime.now(UTC)
            and bool(receipt.get("manifest_digest"))
            and bool(receipt.get("manifest_signature"))
        )

    return validate


def load_pointer(
    path: Path,
    *,
    fallback_root: str,
    fallback_revision: str,
    fallback_version: str,
    data_root: str = "",
) -> dict[str, Any]:
    root = Path(fallback_root).resolve(strict=True)
    fallback = {
        "schema_version": 1,
        "generation": 0,
        "revision": fallback_revision,
        "tree_sha": fallback_revision,
        "root": str(root),
        "version": fallback_version,
        "runner": "local",
        "launch_argv": [
            sys.executable, "-m", "uvicorn", "web_app.app:app",
            "--host", "{host}", "--port", "{port}",
        ],
        "manifest_digest": "fallback:" + fallback_revision,
        "activated_at": _utc_now(),
        "previous_revision": None,
        "known_good": True,
        "data_root": data_root,
    }
    store = PointerStore(path)
    store.ensure_known_good(fallback)
    store.refresh_mutable_fallback(fallback)
    return store.set_missing_defaults({"data_root": data_root})


def command_for(pointer: dict[str, Any], *, python: str, host: str, port: int) -> list[str]:
    return [
        item.format(host=host, port=port, python=python)
        for item in pointer.get("launch_argv", [])
    ]


def _http_probe(host: str, port: int, expected_revision: str) -> bool:
    from urllib.request import Request, urlopen

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            nonce = os.urandom(16).hex()
            request = Request(
                f"http://{host}:{port}/api/health",
                headers={"X-JSON-CODR-Health-Nonce": nonce},
            )
            with urlopen(request, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if (
                response.status == 200
                and payload.get("revision") == expected_revision
                and payload.get("health_nonce") == nonce
            ):
                return True
        except (OSError, ValueError):
            time.sleep(0.1)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer", required=True)
    parser.add_argument("--fallback-root", required=True)
    parser.add_argument("--fallback-revision", required=True)
    parser.add_argument("--fallback-version", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-root")
    parser.add_argument("--docker-distro", default="Ubuntu")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--request-shutdown", action="store_true")
    arguments = parser.parse_args(argv)
    pointer = load_pointer(
        Path(arguments.pointer),
        fallback_root=arguments.fallback_root,
        fallback_revision=arguments.fallback_revision,
        fallback_version=arguments.fallback_version,
        data_root=arguments.data_root or "",
    )
    command = command_for(
        pointer, python=arguments.python, host=arguments.host, port=arguments.port
    )
    if arguments.validate_only:
        print(json.dumps({
            "pointer": pointer,
            "command": command,
            "data_root": pointer.get("data_root", ""),
        }))
        return 0
    state_root = Path(arguments.pointer).resolve().parent.parent
    key = _load_supervisor_key(state_root / "security" / "supervisor.key")
    if arguments.request_shutdown:
        send_shutdown_request(state_root / "control", key)
        return 0
    runner = HybridRunner(distro=arguments.docker_distro)
    supervisor = StableSupervisor(
        PointerStore(Path(arguments.pointer)),
        runner=runner,
        probe=_http_probe,
        host=arguments.host,
        port=arguments.port,
        receipt_validator=health_receipt_validator(key),
    )
    control = SupervisorControl(state_root / "control", supervisor, key=key)
    try:
        supervisor.initialize(pointer)
        control.serve()
    except KeyboardInterrupt:
        return 0
    finally:
        supervisor.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
