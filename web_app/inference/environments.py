from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from web_app.inference.contracts import ProviderKind


PACKAGES = {
    ProviderKind.openvino: ("openvino-genai==2025.4", "openvino-tokenizers==2025.4", "huggingface-hub==0.36.0", "pydantic==2.14.3"),
    ProviderKind.ryzen_ai: ("onnxruntime-genai==0.19.0", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
    ProviderKind.winml: ("onnxruntime-genai==0.19.0", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
    ProviderKind.directml: ("onnxruntime-genai-directml==0.12.2", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
}

OPENVINO_LOCK = Path(__file__).resolve().parents[2] / "requirements-openvino-lock.txt"


def find_compatible_python() -> Path:
    configured = os.environ.get("JSON_CODR_COMPATIBLE_PYTHON")
    if configured:
        candidate = Path(configured)
        result = subprocess.run(
            [str(candidate), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode == 0 and result.stdout.strip() in {"3.11", "3.12"}:
            return candidate
        raise RuntimeError(
            "JSON_CODR_COMPATIBLE_PYTHON must point to a working Python 3.11 or 3.12 executable"
        )
    if (3, 11) <= sys.version_info[:2] <= (3, 12):
        return Path(sys.executable)
    if sys.platform == "win32" and shutil.which("py"):
        for selector in ("-3.12", "-3.11"):
            result = subprocess.run(
                ["py", selector, "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
    for command in ("python3.12", "python3.11"):
        executable = shutil.which(command)
        if executable:
            return Path(executable)
    raise RuntimeError("Optional hardware runtimes require Python 3.11 or 3.12")


@dataclass(frozen=True)
class EnvironmentPlan:
    provider: ProviderKind
    root: Path
    python: Path
    packages: tuple[str, ...]


class EnvironmentManager:
    RECEIPT_NAME = ".json_codr_verified.json"

    def __init__(self, data_root: Path, base_python: Path | None = None) -> None:
        self.root = Path(data_root).resolve() / "inference-providers"
        self.base_python = Path(base_python) if base_python else None

    def _base_python(self) -> Path:
        if self.base_python is None:
            self.base_python = find_compatible_python()
        return self.base_python

    def plan(self, provider: ProviderKind) -> EnvironmentPlan:
        if provider not in PACKAGES:
            raise ValueError("Ollama does not use an optional provider environment")
        root = self.root / provider.value
        python = root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        return EnvironmentPlan(provider, root, python, PACKAGES[provider])

    def install_command(self, provider: ProviderKind) -> str:
        plan = self.plan(provider)
        install_target = (
            f'--require-hashes -r "{OPENVINO_LOCK}"'
            if provider is ProviderKind.openvino
            else " ".join(plan.packages)
        )
        return "; ".join((
            f'$providerPython = "{plan.python}"',
            f'$approvedProviderPackages = "{" ".join(plan.packages)}"',
            "$rebuildProviderEnvironment = -not (Test-Path -LiteralPath $providerPython)",
            "if (-not $rebuildProviderEnvironment) { "
            "& $providerPython -c 'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 11), (3, 12)))'; "
            "$rebuildProviderEnvironment = $LASTEXITCODE -ne 0 }",
            f'if ($rebuildProviderEnvironment) {{ & "{self._base_python()}" -m venv --clear "{plan.root}"; '
            "if ($LASTEXITCODE -ne 0) { throw 'Provider environment creation failed' } }",
            f"& $providerPython -m pip --disable-pip-version-check --no-input install {install_target}",
        ))

    @staticmethod
    def _python_version(python: Path) -> tuple[int, int] | None:
        try:
            result = subprocess.run(
                [str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            major, minor = result.stdout.strip().split(".", 1)
            return (int(major), int(minor)) if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None

    def _runtime_importable(self, provider: ProviderKind) -> bool:
        module = "openvino_genai" if provider is ProviderKind.openvino else "onnxruntime_genai"
        try:
            result = subprocess.run(
                [str(self.plan(provider).python), "-c", f"import {module}"],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def provider_devices(self, provider: ProviderKind) -> list[str]:
        if provider is ProviderKind.openvino:
            code = "import json, openvino as ov; print(json.dumps(ov.Core().available_devices))"
        else:
            code = "import json, onnxruntime as ort; print(json.dumps(ort.get_available_providers()))"
        try:
            result = subprocess.run(
                [str(self.plan(provider).python), "-c", code],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            value = json.loads(result.stdout.strip()) if result.returncode == 0 else []
            return [str(item) for item in value] if isinstance(value, list) else []
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return []

    def model_ready(self, provider: ProviderKind, models=None) -> bool:
        if models is None:
            from web_app.inference.catalog import OptimizedModelCatalog

            models = OptimizedModelCatalog().list()
        return any(
            model.provider is provider and self.verify_model(model, require_probe=True)
            for model in models
        )

    def status(self, provider: ProviderKind) -> dict:
        plan = self.plan(provider)
        if not plan.python.is_file():
            return {
                "provider": provider.value,
                "environment": str(plan.root),
                "installed": False,
                "compatible": False,
                "status": "missing",
                "python_version": None,
                "packages": plan.packages,
            }
        version = self._python_version(plan.python)
        compatible_python = version in {(3, 11), (3, 12)}
        runtime_ready = compatible_python and self._runtime_importable(provider)
        return {
            "provider": provider.value,
            "environment": str(plan.root),
            "installed": True,
            "compatible": runtime_ready,
            "status": "ready" if runtime_ready else "incomplete" if compatible_python else "incompatible",
            "python_version": ".".join(map(str, version)) if version else None,
            "packages": plan.packages,
        }

    def remove(self, provider: ProviderKind) -> None:
        plan = self.plan(provider)
        if plan.root.is_dir():
            shutil.rmtree(plan.root)

    def model_path(self, model) -> Path:
        return self.root.parent / "optimized-models" / model.provider.value / model.repository.replace("/", "--")

    def verification_receipt_path(self, model) -> Path:
        return self.model_path(model) / self.RECEIPT_NAME

    @staticmethod
    def verification_payload(model, probe_verified: bool, evidence: dict | None = None) -> dict:
        return {
            "schema_version": "1",
            "model_id": model.id,
            "repository": model.repository,
            "revision": model.revision,
            "provider": model.provider.value,
            "device": model.device,
            "artifacts": [artifact.model_dump(mode="json") for artifact in model.artifacts],
            "probe_verified": bool(probe_verified),
            "evidence": evidence or {},
        }

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
        except OSError:
            return True

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _validate_model_files(self, root: Path, model) -> bool:
        try:
            root = root.resolve(strict=True)
            total = 0
            for item in root.rglob("*"):
                if item.is_symlink() or self._is_reparse(item):
                    return False
                if item.is_file():
                    total += item.stat().st_size
            if model.maximum_download_bytes is not None and total > model.maximum_download_bytes:
                return False
            if not model.artifacts:
                return False
            for artifact in model.artifacts:
                path = root / artifact.path
                if not path.is_file() or path.is_symlink() or self._is_reparse(path):
                    return False
                if path.stat().st_size != artifact.size or self._sha256(path) != artifact.sha256:
                    return False
            return True
        except (OSError, ValueError):
            return False

    def verify_model(self, model, require_probe: bool = True) -> bool:
        target = self.model_path(model)
        receipt_path = self.verification_receipt_path(model)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        expected = self.verification_payload(
            model,
            probe_verified=bool(receipt.get("probe_verified")),
            evidence=receipt.get("evidence") if isinstance(receipt.get("evidence"), dict) else {},
        )
        for key in ("schema_version", "model_id", "repository", "revision", "provider", "device", "artifacts"):
            if receipt.get(key) != expected[key]:
                return False
        if require_probe and receipt.get("probe_verified") is not True:
            return False
        return self._validate_model_files(target, model)

    def mark_verified(self, model, evidence: dict) -> None:
        if not self.verify_model(model, require_probe=False):
            raise RuntimeError("Optimized model artifacts are not verified")
        receipt = self.verification_receipt_path(model)
        temporary = receipt.with_suffix(receipt.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.verification_payload(model, probe_verified=True, evidence=evidence), sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, receipt)

    def verified_models(self, catalog) -> set[str]:
        return {model.id for model in catalog.list() if self.verify_model(model, require_probe=True)}

    def model_install_command(self, model) -> str:
        plan = self.plan(model.provider)
        target = self.model_path(model)
        return (
            f'& "{plan.python}" -m huggingface_hub.commands.huggingface_cli download '
            f'"{model.repository}" --revision "{model.revision}" --local-dir "{target}"'
        )

    def install_environment(self, provider: ProviderKind, timeout: int = 1800) -> EnvironmentPlan:
        plan = self.plan(provider)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if not plan.python.is_file():
            result = subprocess.run(
                [str(self._base_python()), "-m", "venv", "--clear", str(plan.root)],
                capture_output=True, text=True, timeout=300, creationflags=flags,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Provider environment creation failed")
        install_arguments = (
            ["--require-hashes", "-r", str(OPENVINO_LOCK)]
            if provider is ProviderKind.openvino
            else list(plan.packages)
        )
        result = subprocess.run(
            [str(plan.python), "-m", "pip", "--disable-pip-version-check", "--no-input", "install", *install_arguments],
            capture_output=True, text=True, timeout=timeout, creationflags=flags,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Provider runtime installation failed")
        return plan

    def install_model(self, model, timeout: int = 7200) -> Path:
        if self.verify_model(model, require_probe=False):
            return self.model_path(model)
        plan = self.plan(model.provider)
        if self.status(model.provider)["status"] != "ready":
            plan = self.install_environment(model.provider)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        target = self.model_path(model)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.staging"
        code = (
            "import sys; from huggingface_hub import snapshot_download; "
            "snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])"
        )
        try:
            result = subprocess.run(
                [str(plan.python), "-c", code, model.repository, model.revision, str(staging)],
                capture_output=True, text=True, timeout=timeout, creationflags=flags,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Optimized model download failed")
            if not self._validate_model_files(staging, model):
                raise RuntimeError("Optimized model failed size, path, or checksum verification")
            (staging / self.RECEIPT_NAME).write_text(
                json.dumps(self.verification_payload(model, probe_verified=False), sort_keys=True),
                encoding="utf-8",
            )
            displaced = None
            if target.exists():
                displaced = target.parent / f".{target.name}.{uuid.uuid4().hex}.incomplete"
                os.replace(target, displaced)
            try:
                os.replace(staging, target)
            except Exception:
                if displaced is not None and displaced.exists() and not target.exists():
                    os.replace(displaced, target)
                raise
            if displaced is not None and displaced.exists():
                if displaced.is_symlink():
                    displaced.unlink()
                elif self._is_reparse(displaced):
                    os.rmdir(displaced)
                else:
                    shutil.rmtree(displaced)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)
