import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.intel_npu_bootstrap import IntelNpuProvisioner


class FakeManager:
    def __init__(self, root: Path, devices=("CPU", "NPU")):
        self.root = root / "inference-providers"
        self.devices = list(devices)
        self.environment_installs = 0
        self.model_installs = 0
        self.verified = []

    def install_environment(self, provider):
        self.environment_installs += 1
        return SimpleNamespace(python=Path("C:/provider/python.exe"))

    def provider_devices(self, provider):
        return self.devices

    def install_model(self, model):
        self.model_installs += 1
        path = self.root.parent / "optimized-models" / model.provider.value / "model"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def mark_verified(self, model, evidence):
        self.verified.append((model.id, evidence))


class FakeProvider:
    def __init__(self, success=True):
        self.success = success
        self.probes = 0

    async def probe(self, model):
        self.probes += 1
        return SimpleNamespace(success=self.success, error=None if self.success else "probe failed")


class IntelNpuProvisionerTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_intel_machine_performs_no_provider_or_model_install(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager(Path(directory))
            provider = FakeProvider()
            provisioner = IntelNpuProvisioner(
                Path(directory), manager=manager,
                device_names=lambda: ["NVIDIA GPU"], provider_factory=lambda *_: provider,
            )

            result = await provisioner.run()

            self.assertEqual(result["state"], "skipped")
            self.assertEqual(manager.environment_installs, 0)
            self.assertEqual(manager.model_installs, 0)
            self.assertEqual(provider.probes, 0)

    async def test_intel_hardware_without_openvino_npu_does_not_download_model(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager(Path(directory), devices=("CPU", "GPU"))
            provider = FakeProvider()
            provisioner = IntelNpuProvisioner(
                Path(directory), manager=manager,
                device_names=lambda: ["Intel(R) AI Boost"], provider_factory=lambda *_: provider,
            )

            result = await provisioner.run()

            self.assertEqual(result["state"], "unavailable")
            self.assertEqual(manager.environment_installs, 1)
            self.assertEqual(manager.model_installs, 0)
            self.assertFalse(manager.verified)

    async def test_working_intel_npu_installs_pinned_model_and_persists_probe_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager(Path(directory))
            provider = FakeProvider()
            provisioner = IntelNpuProvisioner(
                Path(directory), manager=manager,
                device_names=lambda: ["Intel(R) AI Boost"], provider_factory=lambda *_: provider,
            )

            result = await provisioner.run()

            model = OptimizedModelCatalog().list()[0]
            self.assertEqual(result["state"], "ready")
            self.assertEqual(result["model_id"], model.id)
            self.assertEqual(result["revision"], model.revision)
            self.assertEqual(manager.model_installs, 1)
            self.assertEqual(provider.probes, 1)
            self.assertEqual(manager.verified[0][0], model.id)
            self.assertEqual(manager.verified[0][1]["device"], "NPU")

    async def test_failed_generation_probe_never_marks_model_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager(Path(directory))
            provider = FakeProvider(success=False)
            provisioner = IntelNpuProvisioner(
                Path(directory), manager=manager,
                device_names=lambda: ["Intel NPU"], provider_factory=lambda *_: provider,
            )

            result = await provisioner.run()

            self.assertEqual(result["state"], "unavailable")
            self.assertFalse(manager.verified)


if __name__ == "__main__":
    unittest.main()
