from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen
from uuid import uuid7

from pydantic import Field

from web_app.core.contracts import FrozenContract


class ActiveBuildPointer(FrozenContract):
    revision: str
    root: str
    version: str
    activated_at: datetime
    previous_revision: str | None = None


class HealthReceipt(FrozenContract):
    health_id: str
    candidate_id: str
    revision: str | None
    root: str
    version: str | None
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


class ActivationReceipt(FrozenContract):
    activation_id: str
    health_id: str
    revision: str
    previous_revision: str | None
    active_pointer: ActiveBuildPointer
    previous_pointer: ActiveBuildPointer | None
    status: Literal["activated"] = "activated"
    activated_at: datetime


class RollbackReceipt(FrozenContract):
    rollback_id: str
    activation_id: str
    failed_revision: str
    restored_revision: str
    restored_pointer: ActiveBuildPointer
    status: Literal["rolled_back"] = "rolled_back"
    rolled_back_at: datetime


class CandidateHealthError(RuntimeError):
    def __init__(self, receipt: HealthReceipt) -> None:
        self.receipt = receipt
        super().__init__(receipt.error or "candidate health check failed")


class ActivationError(RuntimeError):
    def __init__(self, message: str, rollback_receipt: RollbackReceipt) -> None:
        self.rollback_receipt = rollback_receipt
        super().__init__(message)


class ActiveBuildStore:
    """Launcher-owned, atomic typed state stored outside replaceable build roots."""

    def __init__(
        self,
        state_root: str | Path,
        *,
        replacer: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
    ) -> None:
        self.root = Path(state_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pointer_path = self.root / "active-build.json"
        self.activations_root = self.root / "activations"
        self.rollbacks_root = self.root / "rollbacks"
        self.activations_root.mkdir(exist_ok=True)
        self.rollbacks_root.mkdir(exist_ok=True)
        self._replace = replacer

    def load(self) -> ActiveBuildPointer | None:
        if not self.pointer_path.is_file():
            return None
        return ActiveBuildPointer.model_validate_json(
            self.pointer_path.read_text(encoding="utf-8")
        )

    def write(self, pointer: ActiveBuildPointer) -> ActiveBuildPointer:
        self._atomic_write(self.pointer_path, pointer.model_dump_json(indent=2))
        return pointer

    def save_activation(self, receipt: ActivationReceipt) -> None:
        self._atomic_write(
            self.activations_root / f"{receipt.activation_id}.json",
            receipt.model_dump_json(indent=2),
        )

    def activation(self, activation_id: str) -> ActivationReceipt:
        path = self.activations_root / f"{self._safe_id(activation_id)}.json"
        if not path.is_file():
            raise KeyError(activation_id)
        return ActivationReceipt.model_validate_json(path.read_text(encoding="utf-8"))

    def save_rollback(self, receipt: RollbackReceipt) -> None:
        self._atomic_write(
            self.rollbacks_root / f"{receipt.activation_id}.json",
            receipt.model_dump_json(indent=2),
        )

    def rollback(self, activation_id: str) -> RollbackReceipt | None:
        path = self.rollbacks_root / f"{self._safe_id(activation_id)}.json"
        if not path.is_file():
            return None
        return RollbackReceipt.model_validate_json(path.read_text(encoding="utf-8"))

    def _atomic_write(self, target: Path, content: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _safe_id(value: str) -> str:
        if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value):
            raise ValueError("launcher receipt id is invalid")
        return value


class UpdateLauncher:
    def __init__(
        self,
        state_root: str | Path,
        *,
        pointer_store: ActiveBuildStore | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        http_probe: Callable[[str, float], Mapping[str, Any]] | None = None,
        browser_probe: Callable[[str], Mapping[str, Any]] | None = None,
        post_activation_probe: Callable[[ActiveBuildPointer, HealthReceipt], bool] | None = None,
        port_allocator: Callable[[], int] | None = None,
        port_available: Callable[[int], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.pointer_store = pointer_store or ActiveBuildStore(self.state_root / "pointer")
        self._process_factory = process_factory
        self._http_probe = http_probe or self._default_http_probe
        self._browser_probe = browser_probe or self._default_browser_probe
        self._post_activation_probe = post_activation_probe or (lambda _pointer, _receipt: True)
        self._port_allocator = port_allocator or self._allocate_port
        self._port_available = port_available or self._is_port_available
        self._sleep = sleep
        self._monotonic = monotonic
        self._processes: dict[str, Any] = {}

    def launch_candidate(self, candidate, profile) -> HealthReceipt:
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        revision = getattr(candidate, "commit_sha", None)
        worktree = getattr(candidate, "worktree", None)
        root_value = getattr(worktree, "working_root", "")
        root = Path(root_value).resolve() if root_value else Path()
        version = getattr(profile, "expected_version", None)
        migration = str(getattr(profile, "migration_compatibility", ""))
        health_id = f"health-{uuid7()}"
        data_root = self.state_root / "candidate-data" / health_id
        port = 0
        process = None
        checks: list[str] = []
        browser_errors: tuple[str, ...] = ()

        def failure(message: str) -> CandidateHealthError:
            if process is not None:
                self._terminate(process)
            return CandidateHealthError(HealthReceipt(
                health_id=health_id,
                candidate_id=candidate_id or "unknown-candidate",
                revision=revision,
                root=str(root),
                version=version,
                port=port,
                data_root=str(data_root),
                pid=None if process is None else getattr(process, "pid", None),
                healthy=False,
                checks=tuple(checks),
                browser_fatal_errors=browser_errors,
                error=message,
                migration_compatibility=migration or "unknown",
            ))

        if migration != "backward_compatible":
            raise failure("candidate migration is not backward compatible")
        if not candidate_id or not revision or not root.is_dir():
            raise failure("candidate launch identity or root is invalid")
        if not version:
            raise failure("candidate expected version is not configured")
        launch_argv = tuple(getattr(profile, "launch_argv", ()))
        if not launch_argv:
            raise failure("candidate launch profile has no server-owned command")
        port = self._port_allocator()
        if not self._port_available(port):
            raise failure(f"candidate loopback port {port} is unavailable")
        data_root.mkdir(parents=True, exist_ok=False)
        arguments = [
            argument.format(host="127.0.0.1", port=port)
            for argument in launch_argv
        ]
        if not any("{host}" in argument or "--host" == argument for argument in launch_argv):
            arguments.extend(("--host", "127.0.0.1"))
        if not any("{port}" in argument or "--port" == argument for argument in launch_argv):
            arguments.extend(("--port", str(port)))
        environment = {
            **os.environ,
            "JSON_CODR_REVISION": revision,
            "JSON_CODR_EXPECTED_VERSION": version,
            "JSON_CODR_DATA_ROOT": str(data_root),
            "JSON_CODR_HOST": "127.0.0.1",
            "JSON_CODR_PORT": str(port),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        try:
            process = self._process_factory(
                arguments,
                cwd=str(root),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._processes[health_id] = process
            if process.poll() is not None:
                raise failure(f"candidate process exited with code {process.poll()}")
            checks.append("startup")
            base_url = f"http://127.0.0.1:{port}"
            deadline = self._monotonic() + float(getattr(profile, "startup_timeout_seconds", 30))
            while True:
                try:
                    health = dict(self._http_probe(f"{base_url}/api/health", 2.0))
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
            checks.append("api")
            openapi = dict(self._http_probe(f"{base_url}/openapi.json", 2.0))
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
        return HealthReceipt(
            health_id=health_id,
            candidate_id=candidate_id,
            revision=revision,
            root=str(root),
            version=version,
            port=port,
            data_root=str(data_root),
            pid=getattr(process, "pid", None),
            healthy=True,
            checks=tuple(checks),
            browser_fatal_errors=(),
            migration_compatibility=migration,
        )

    def activate(self, receipt: HealthReceipt | Mapping[str, Any]) -> ActivationReceipt:
        health = receipt if isinstance(receipt, HealthReceipt) else HealthReceipt.model_validate(receipt)
        if not health.healthy or not health.revision or not health.version:
            raise PermissionError("activation requires a healthy typed receipt")
        if health.migration_compatibility != "backward_compatible":
            raise PermissionError("activation requires a backward-compatible migration")
        candidate_root = Path(health.root).resolve(strict=True)
        if self.pointer_store.root == candidate_root or self.pointer_store.root.is_relative_to(candidate_root):
            raise PermissionError("active-build pointer must remain outside candidate roots")
        previous = self.pointer_store.load()
        now = datetime.now(UTC)
        pointer = ActiveBuildPointer(
            revision=health.revision,
            root=str(candidate_root),
            version=health.version,
            activated_at=now,
            previous_revision=None if previous is None else previous.revision,
        )
        activation = ActivationReceipt(
            activation_id=f"activation-{uuid7()}",
            health_id=health.health_id,
            revision=health.revision,
            previous_revision=None if previous is None else previous.revision,
            active_pointer=pointer,
            previous_pointer=previous,
            activated_at=now,
        )
        self.pointer_store.write(pointer)
        try:
            self.pointer_store.save_activation(activation)
        except Exception:
            if previous is not None:
                self.pointer_store.write(previous)
            raise
        try:
            healthy = bool(self._post_activation_probe(pointer, health))
        except Exception:
            healthy = False
        if not healthy:
            rollback = self.rollback(activation.activation_id)
            raise ActivationError(
                "post-activation health failed; previous build was restored", rollback
            )
        return activation

    def rollback(self, activation_id: str) -> RollbackReceipt:
        existing = self.pointer_store.rollback(activation_id)
        if existing is not None:
            return existing
        activation = self.pointer_store.activation(activation_id)
        previous = activation.previous_pointer
        if previous is None:
            raise PermissionError("activation has no previous known-good build")
        current = self.pointer_store.load()
        if current is None or current.revision != activation.active_pointer.revision:
            raise PermissionError("active build changed after this activation")
        restored = previous.model_copy(update={
            "activated_at": datetime.now(UTC),
            "previous_revision": activation.active_pointer.revision,
        })
        self.pointer_store.write(restored)
        receipt = RollbackReceipt(
            rollback_id=f"rollback-{uuid7()}",
            activation_id=activation_id,
            failed_revision=activation.active_pointer.revision,
            restored_revision=restored.revision,
            restored_pointer=restored,
            rolled_back_at=datetime.now(UTC),
        )
        self.pointer_store.save_rollback(receipt)
        return receipt

    def terminate_health(self, health_id: str) -> None:
        process = self._processes.pop(health_id, None)
        if process is not None:
            self._terminate(process)

    @staticmethod
    def _terminate(process: Any) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, TimeoutError):
            process.kill()
            process.wait(timeout=5)

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

    @staticmethod
    def _default_http_probe(url: str, timeout: float) -> Mapping[str, Any]:
        with urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                raise OSError(f"HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_browser_probe(base_url: str) -> Mapping[str, Any]:
        with urlopen(base_url, timeout=5) as response:
            return {"loaded": response.status == 200, "fatal_errors": ()}
