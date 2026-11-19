import unittest
from unittest.mock import patch

from web_app.inference.contracts import ProviderKind
from web_app.inference.detection import AcceleratorDetector


class AcceleratorDetectionTests(unittest.TestCase):
    def detector(
        self,
        devices=(),
        runtimes=None,
        provider_devices=None,
        os_build=26100,
        directx12=False,
        models=None,
    ):
        return AcceleratorDetector(
            device_names=lambda: list(devices),
            runtime_available=lambda name: (runtimes or {}).get(name, False),
            provider_devices=lambda name: (provider_devices or {}).get(name, []),
            windows_build=lambda: os_build,
            directx12_available=lambda: directx12,
            model_ready=lambda name: (models or {}).get(name, False),
        )

    def test_intel_npu_reports_hardware_runtime_model_and_provider_evidence(self):
        states = self.detector(
            devices=["Intel(R) AI Boost"],
            runtimes={"openvino": True},
            provider_devices={"openvino": ["CPU", "GPU", "NPU"]},
            models={"openvino": True},
        ).detect()
        state = next(item for item in states if item.provider is ProviderKind.openvino)

        self.assertTrue(state.hardware_detected)
        self.assertTrue(state.runtime_ready)
        self.assertTrue(state.model_ready)
        self.assertIn("OpenVINO device: NPU", state.evidence)

    def test_amd_npu_requires_ryzen_runtime_and_supported_provider_device(self):
        missing = self.detector(devices=["AMD Ryzen AI NPU"]).detect()
        missing_state = next(item for item in missing if item.provider is ProviderKind.ryzen_ai)
        self.assertTrue(missing_state.hardware_detected)
        self.assertFalse(missing_state.runtime_ready)
        self.assertIn("runtime", missing_state.reason.lower())

        ready = self.detector(
            devices=["AMD Ryzen AI NPU"],
            runtimes={"ryzen_ai": True},
            provider_devices={"ryzen_ai": ["NPU", "hybrid"]},
        ).detect()
        self.assertTrue(next(item for item in ready if item.provider is ProviderKind.ryzen_ai).runtime_ready)

    def test_generic_npu_is_detected_without_claiming_a_compatible_provider(self):
        states = self.detector(devices=["Contoso Neural Processing Unit"]).detect()

        self.assertEqual([item.provider for item in states], [ProviderKind.winml])
        self.assertTrue(states[0].hardware_detected)
        self.assertFalse(states[0].runtime_ready)
        self.assertIn("WinML", states[0].reason)
        self.assertEqual(self.detector(devices=["USB Input Device"]).detect(), [])

    def test_winml_requires_windows_11_24h2_and_directml_is_gpu(self):
        states = self.detector(
            devices=["Intel(R) AI Boost"],
            runtimes={"winml": True, "directml": True},
            provider_devices={"winml": ["NPU"], "directml": ["DML"]},
            os_build=26100,
            directx12=True,
        ).detect()
        winml = next(item for item in states if item.provider is ProviderKind.winml)
        directml = next(item for item in states if item.provider is ProviderKind.directml)

        self.assertTrue(winml.runtime_ready)
        self.assertEqual(winml.kind, "npu")
        self.assertTrue(directml.runtime_ready)
        self.assertEqual(directml.kind, "gpu")

        old_windows = self.detector(runtimes={"winml": True}, os_build=22631).detect()
        self.assertFalse(next(item for item in old_windows if item.provider is ProviderKind.winml).runtime_ready)

    def test_duplicate_device_names_are_deduplicated(self):
        states = self.detector(
            devices=["Intel(R) AI Boost", "Intel(R) AI Boost"],
            runtimes={"openvino": True},
            provider_devices={"openvino": ["NPU"]},
        ).detect()
        openvino = next(item for item in states if item.provider is ProviderKind.openvino)
        self.assertEqual(openvino.evidence.count("Hardware: Intel(R) AI Boost"), 1)

    def test_directx_detection_never_launches_dxdiag(self):
        with patch("web_app.inference.detection.os.name", "nt"), patch(
            "web_app.inference.detection.subprocess.run"
        ) as run:
            AcceleratorDetector._directx12_available()

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
