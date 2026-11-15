from __future__ import annotations

import ctypes
import importlib.util
import os
import platform
import re
import subprocess
from collections.abc import Callable

from web_app.inference.contracts import ProviderKind, ProviderState


class AcceleratorDetector:
    def __init__(
        self,
        device_names: Callable[[], list[str]] | None = None,
        runtime_available: Callable[[str], bool] | None = None,
        provider_devices: Callable[[str], list[str]] | None = None,
        windows_build: Callable[[], int] | None = None,
        directx12_available: Callable[[], bool] | None = None,
        model_ready: Callable[[str], bool] | None = None,
    ) -> None:
        self.device_names = device_names or self._windows_devices
        self.runtime_available = runtime_available or self._runtime_available
        self.provider_devices = provider_devices or (lambda provider: [])
        self.windows_build = windows_build or self._windows_build
        self.directx12_available = directx12_available or self._directx12_available
        self.model_ready = model_ready or (lambda provider: False)

    def detect(self) -> list[ProviderState]:
        devices = list(dict.fromkeys(name.strip() for name in self.device_names() if name.strip()))
        intel = [name for name in devices if re.search(r"(?i)(intel.*AI Boost|intel.*NPU)", name)]
        amd = [name for name in devices if re.search(r"(?i)(AMD.*Ryzen AI|AMD.*NPU)", name)]
        generic_npu = [name for name in devices if self.is_npu_name(name)]
        result: list[ProviderState] = []

        openvino_runtime = self.runtime_available("openvino")
        if intel or openvino_runtime:
            provider_devices = self.provider_devices("openvino") if openvino_runtime else []
            runtime_ready = openvino_runtime and "NPU" in {item.upper() for item in provider_devices}
            result.append(self._state(
                ProviderKind.openvino, "Intel OpenVINO GenAI", "npu", intel, runtime_ready,
                self.model_ready("openvino"), [f"OpenVINO device: {item}" for item in provider_devices],
                None if runtime_ready else "OpenVINO NPU runtime or driver is unavailable.",
            ))

        ryzen_runtime = self.runtime_available("ryzen_ai")
        if amd or ryzen_runtime:
            provider_devices = self.provider_devices("ryzen_ai") if ryzen_runtime else []
            runtime_ready = ryzen_runtime and any(item.lower() in {"npu", "hybrid"} for item in provider_devices)
            result.append(self._state(
                ProviderKind.ryzen_ai, "AMD Ryzen AI", "npu", amd, runtime_ready,
                self.model_ready("ryzen_ai"), [f"Ryzen AI device: {item}" for item in provider_devices],
                None if runtime_ready else "Ryzen AI runtime or supported NPU provider is unavailable.",
            ))

        winml_runtime = self.runtime_available("winml")
        if generic_npu or winml_runtime:
            supported_os = self.windows_build() >= 26100
            provider_devices = self.provider_devices("winml") if winml_runtime else []
            runtime_ready = winml_runtime and supported_os and bool(provider_devices)
            result.append(self._state(
                ProviderKind.winml, "Windows ML automatic provider", "npu", generic_npu,
                runtime_ready, self.model_ready("winml"),
                [f"WinML provider: {item}" for item in provider_devices],
                None if runtime_ready else "WinML requires Windows 11 24H2 or newer and an available execution provider.",
            ))

        directml_runtime = self.runtime_available("directml")
        directx12 = self.directx12_available()
        if directx12 or directml_runtime:
            provider_devices = self.provider_devices("directml") if directml_runtime else []
            runtime_ready = directml_runtime and directx12 and bool(provider_devices)
            result.append(self._state(
                ProviderKind.directml, "ONNX Runtime DirectML", "gpu", [], runtime_ready,
                self.model_ready("directml"), ["DirectX 12 available"] + [f"DirectML provider: {item}" for item in provider_devices],
                None if runtime_ready else "DirectML runtime or DirectX 12 device is unavailable.",
                hardware_detected=directx12,
            ))
        return result

    @staticmethod
    def _state(
        provider: ProviderKind,
        name: str,
        kind: str,
        hardware: list[str],
        runtime_ready: bool,
        model_ready: bool,
        evidence: list[str],
        reason: str | None,
        hardware_detected: bool | None = None,
    ) -> ProviderState:
        return ProviderState(
            provider=provider,
            name=name,
            kind=kind,
            hardware_detected=bool(hardware) if hardware_detected is None else hardware_detected,
            runtime_ready=runtime_ready,
            model_ready=model_ready,
            evidence=[*(f"Hardware: {item}" for item in hardware), *evidence],
            reason=reason,
        )

    @staticmethod
    def is_npu_name(name: str) -> bool:
        return bool(re.search(
            r"(?i)(?:\bNPU\b|neural (?:processing unit|processor)|intel(?:\(r\))? AI Boost|AMD Ryzen AI|Qualcomm Hexagon)",
            name,
        ))

    @staticmethod
    def _runtime_available(provider: str) -> bool:
        modules = {
            "openvino": "openvino_genai",
            "ryzen_ai": "onnxruntime_genai",
            "winml": "onnxruntime_genai",
            "directml": "onnxruntime_genai",
        }
        return importlib.util.find_spec(modules[provider]) is not None

    @staticmethod
    def _windows_build() -> int:
        if os.name != "nt":
            return 0
        try:
            return int(platform.version().split(".")[-1])
        except ValueError:
            return 0

    @staticmethod
    def _directx12_available() -> bool:
        if os.name != "nt":
            return False
        try:
            library = ctypes.WinDLL("d3d12.dll")
        except (AttributeError, OSError):
            return False
        return hasattr(library, "D3D12CreateDevice")

    @staticmethod
    def _windows_devices() -> list[str]:
        if os.name != "nt":
            return []
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "Get-CimInstance Win32_PnPEntity | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
