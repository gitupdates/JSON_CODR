from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from web_app.inference.contracts import ProviderKind


PACKAGES = {
    ProviderKind.openvino: ("openvino-genai==2025.4", "openvino-tokenizers==2025.4", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
    ProviderKind.ryzen_ai: ("onnxruntime-genai==0.19.0", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
    ProviderKind.winml: ("onnxruntime-genai==0.19.0", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
    ProviderKind.directml: ("onnxruntime-genai-directml==0.12.2", "huggingface-hub==0.36.0", "pydantic>=2,<3"),
}


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
    def __init__(self, data_root: Path, base_python: Path | None = None) -> None:
        self.root = Path(data_root).resolve() / "inference-providers"
        self.base_python = Path(base_python) if base_python else find_compatible_python()

    def plan(self, provider: ProviderKind) -> EnvironmentPlan:
        if provider not in PACKAGES:
            raise ValueError("Ollama does not use an optional provider environment")
        root = self.root / provider.value
        python = root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        return EnvironmentPlan(provider, root, python, PACKAGES[provider])

    def install_command(self, provider: ProviderKind) -> str:
        plan = self.plan(provider)
        packages = " ".join(plan.packages)
        return "; ".join((
            f'$providerPython = "{plan.python}"',
            "$rebuildProviderEnvironment = -not (Test-Path -LiteralPath $providerPython)",
            "if (-not $rebuildProviderEnvironment) { "
            "& $providerPython -c 'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 11), (3, 12)))'; "
            "$rebuildProviderEnvironment = $LASTEXITCODE -ne 0 }",
            f'if ($rebuildProviderEnvironment) {{ & "{self.base_python}" -m venv --clear "{plan.root}"; '
            "if ($LASTEXITCODE -ne 0) { throw 'Provider environment creation failed' } }",
            f"& $providerPython -m pip --disable-pip-version-check install {packages}",
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

    def model_ready(self, provider: ProviderKind) -> bool:
        root = self.root.parent / "optimized-models" / provider.value
        return root.is_dir() and any(item.is_dir() for item in root.iterdir())

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

    def model_install_command(self, model) -> str:
        plan = self.plan(model.provider)
        target = self.model_path(model)
        return (
            f'& "{plan.python}" -m huggingface_hub.commands.huggingface_cli download '
            f'"{model.repository}" --revision "{model.revision}" --local-dir "{target}"'
        )

    def install_model(self, model, timeout: int = 7200) -> Path:
        plan = self.plan(model.provider)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if not plan.python.is_file():
            result = subprocess.run(
                [str(self.base_python), "-m", "venv", "--clear", str(plan.root)],
                capture_output=True, text=True, timeout=300, creationflags=flags,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Provider environment creation failed")
        result = subprocess.run(
            [str(plan.python), "-m", "pip", "--disable-pip-version-check", "install", *plan.packages],
            capture_output=True, text=True, timeout=1800, creationflags=flags,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Provider runtime installation failed")
        target = self.model_path(model)
        target.parent.mkdir(parents=True, exist_ok=True)
        code = (
            "import sys; from huggingface_hub import snapshot_download; "
            "snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])"
        )
        result = subprocess.run(
            [str(plan.python), "-c", code, model.repository, model.revision, str(target)],
            capture_output=True, text=True, timeout=timeout, creationflags=flags,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Optimized model download failed")
        return target
