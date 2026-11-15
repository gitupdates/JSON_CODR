from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from web_app.inference.contracts import ProviderKind


PACKAGES = {
    ProviderKind.openvino: ("openvino-genai==2025.4", "openvino-tokenizers==2025.4"),
    ProviderKind.ryzen_ai: ("onnxruntime-genai==0.19.0",),
    ProviderKind.winml: ("onnxruntime-genai==0.19.0",),
    ProviderKind.directml: ("onnxruntime-genai-directml==0.19.0",),
}


@dataclass(frozen=True)
class EnvironmentPlan:
    provider: ProviderKind
    root: Path
    python: Path
    packages: tuple[str, ...]


class EnvironmentManager:
    def __init__(self, data_root: Path) -> None:
        self.root = Path(data_root).resolve() / "inference-providers"

    def plan(self, provider: ProviderKind) -> EnvironmentPlan:
        if provider not in PACKAGES:
            raise ValueError("Ollama does not use an optional provider environment")
        root = self.root / provider.value
        python = root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        return EnvironmentPlan(provider, root, python, PACKAGES[provider])

    def install_command(self, provider: ProviderKind) -> str:
        plan = self.plan(provider)
        packages = " ".join(plan.packages)
        return f'"{sys.executable}" -m venv "{plan.root}"; & "{plan.python}" -m pip install {packages}'

    def remove(self, provider: ProviderKind) -> None:
        plan = self.plan(provider)
        if plan.root.is_dir():
            shutil.rmtree(plan.root)
