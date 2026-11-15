from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from web_app.inference.contracts import ProviderKind


PACKAGES = {
    ProviderKind.openvino: ("openvino-genai==2025.4", "openvino-tokenizers==2025.4", "huggingface-hub==0.36.0"),
    ProviderKind.ryzen_ai: ("onnxruntime-genai==0.19.0", "huggingface-hub==0.36.0"),
    ProviderKind.winml: ("onnxruntime-genai==0.19.0", "huggingface-hub==0.36.0"),
    ProviderKind.directml: ("onnxruntime-genai-directml==0.12.2", "huggingface-hub==0.36.0"),
}


def find_compatible_python() -> Path:
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
