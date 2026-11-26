from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Callable
from pathlib import Path

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import ProviderKind
from web_app.inference.detection import AcceleratorDetector
from web_app.inference.environments import EnvironmentManager, PACKAGES
from web_app.inference.providers.openvino import OpenVINOProvider
from web_app.inference.sidecar import SidecarClient


INTEL_NPU_PATTERN = re.compile(
    r"intel(?:\(r\))?.*(?:AI Boost|AI accelerator|\bNPU\b|neural (?:processing unit|processor))",
    re.IGNORECASE,
)


class IntelNpuProvisioner:
    """Conditionally provisions the reviewed Intel NPU path without touching drivers."""

    def __init__(
        self,
        data_root: Path,
        *,
        manager: EnvironmentManager | None = None,
        device_names: Callable[[], list[str]] | None = None,
        provider_factory: Callable[[EnvironmentManager, object], object] | None = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.manager = manager or EnvironmentManager(self.data_root)
        self.device_names = device_names or AcceleratorDetector._windows_devices
        self.model = next(
            model for model in OptimizedModelCatalog().list()
            if model.provider is ProviderKind.openvino and model.device == "NPU"
        )
        self._validate_release_policy()
        self.provider_factory = provider_factory or self._provider

    def _validate_release_policy(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config" / "bootstrap-accelerators.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        provider = next(item for item in policy["providers"] if item["id"] == "intel-openvino-npu")
        expected_model = {
            "id": self.model.id,
            "repository": self.model.repository,
            "revision": self.model.revision,
            "license": self.model.license,
            "maximum_download_bytes": self.model.maximum_download_bytes,
            "artifacts": [artifact.model_dump(mode="json") for artifact in self.model.artifacts],
        }
        if (
            provider.get("condition") != "intel_npu"
            or provider.get("provider") != "openvino"
            or provider.get("device") != "NPU"
            or provider.get("installs_driver") is not False
            or provider.get("lockfile") != "requirements-openvino-lock.txt"
            or provider.get("packages") != list(PACKAGES[ProviderKind.openvino])
            or provider.get("model") != expected_model
        ):
            raise RuntimeError("Intel NPU bootstrap policy does not match the reviewed runtime catalog")

    @staticmethod
    def _intel_devices(names: list[str]) -> list[str]:
        return list(dict.fromkeys(name.strip() for name in names if INTEL_NPU_PATTERN.search(name.strip())))

    @staticmethod
    def _provider(manager: EnvironmentManager, model):
        client = SidecarClient(manager.plan(ProviderKind.openvino).python)
        return OpenVINOProvider(client, manager.root.parent / "optimized-models")

    async def run(self) -> dict:
        hardware = self._intel_devices(self.device_names())
        base = {
            "provider": ProviderKind.openvino.value,
            "model_id": self.model.id,
            "revision": self.model.revision,
            "hardware": hardware,
            "drivers_modified": False,
        }
        if not hardware:
            return {**base, "state": "skipped", "detail": "No Intel NPU hardware was detected."}
        try:
            self.manager.install_environment(ProviderKind.openvino)
            devices = self.manager.provider_devices(ProviderKind.openvino)
            if "NPU" not in {device.upper() for device in devices}:
                return {
                    **base,
                    "state": "unavailable",
                    "detail": "Intel hardware was detected, but OpenVINO did not expose a working NPU device.",
                    "openvino_devices": devices,
                }
            path = self.manager.install_model(self.model)
            provider = self.provider_factory(self.manager, self.model)
            probe = await provider.probe(self.model)
            if not probe.success:
                return {
                    **base,
                    "state": "unavailable",
                    "detail": f"The bounded Intel NPU generation probe failed: {probe.error or 'unknown error'}",
                    "openvino_devices": devices,
                }
            evidence = {
                "device": "NPU",
                "hardware": hardware,
                "openvino_devices": devices,
                "probe": "bounded generation succeeded",
            }
            self.manager.mark_verified(self.model, evidence)
            return {
                **base,
                "state": "ready",
                "detail": "Pinned Intel NPU model and runtime passed a bounded generation probe.",
                "openvino_devices": devices,
                "path": str(path),
            }
        except Exception as error:
            return {
                **base,
                "state": "unavailable",
                "detail": f"Optional Intel NPU provisioning failed without affecting Ollama: {type(error).__name__}: {error}",
            }


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the reviewed JSON_CODR Intel NPU model")
    parser.add_argument("--data-root", type=Path, required=True)
    arguments = parser.parse_args()
    result = asyncio.run(IntelNpuProvisioner(arguments.data_root).run())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
