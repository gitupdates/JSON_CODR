import tempfile
import unittest
import json
from pathlib import Path

from web_app.hardware import HardwareBackendManager
from web_app.inference.detection import AcceleratorDetector


class HardwareBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_ai_device_name_filter_rejects_input_device_false_positive(self):
        self.assertFalse(HardwareBackendManager.is_ai_device_name("USB Input Device"))
        self.assertFalse(HardwareBackendManager.is_ai_device_name("Microsoft Input Configuration Device"))
        self.assertTrue(HardwareBackendManager.is_ai_device_name("Intel(R) AI Boost"))
        self.assertTrue(HardwareBackendManager.is_ai_device_name("Qualcomm Hexagon NPU"))

    def test_cpu_is_universal_and_accelerators_require_detector_and_runtime(self):
        runtime = self.root / "ollama"
        (runtime / "cuda_v12").mkdir(parents=True)
        manager = HardwareBackendManager(
            self.root,
            runtime_root=runtime,
            command_available=lambda command: command == "nvidia-smi",
            ai_device_detector=lambda: [],
            gpu_telemetry_reader=lambda: [],
        )

        result = manager.detect()

        self.assertEqual([item["id"] for item in result], ["cpu", "cuda_v12"])
        self.assertTrue(result[0]["compatible"])
        self.assertFalse(result[1]["verified"])

    def test_detect_orders_ollama_gpu_below_cpu_before_native_runtimes_and_npu(self):
        runtime = self.root / "ollama"
        for backend in ("cuda_v12", "vulkan"):
            (runtime / backend).mkdir(parents=True)
        manager = HardwareBackendManager(
            self.root,
            runtime_root=runtime,
            command_available=lambda command: command in {"nvidia-smi", "vulkaninfo"},
            ai_device_detector=lambda: ["Intel(R) AI Boost"],
            gpu_telemetry_reader=lambda: [{
                "index": 0,
                "name": "NVIDIA GeForce RTX 4060 Laptop GPU",
                "memory_total": 8188,
                "memory_used": 512,
                "memory_free": 7676,
                "utilization": 12,
                "temperature": 47,
            }],
        )

        result = manager.detect()

        self.assertEqual([item["id"] for item in result], ["cpu", "ollama_gpu", "cuda_v12", "vulkan", "npu-0"])
        self.assertEqual(result[1]["name"], "Ollama GPU · NVIDIA GeForce RTX 4060 Laptop GPU")
        self.assertEqual(result[1]["kind"], "gpu")
        self.assertTrue(result[1]["runnable"])
        self.assertEqual(result[1]["readiness"], {
            "hardware": True,
            "driver": True,
            "runtime": True,
            "model": True,
        })

    def test_ai_accelerator_is_reported_but_not_runnable_without_ollama_backend(self):
        manager = HardwareBackendManager(
            self.root,
            ai_device_detector=lambda: ["Intel(R) AI Boost"],
            command_available=lambda command: False,
            environment_writer=lambda name, value: None,
            gpu_telemetry_reader=lambda: [],
        )

        result = manager.detect()
        npu = result[1]

        self.assertEqual(npu["kind"], "npu")
        self.assertEqual(npu["name"], "Intel(R) AI Boost")
        self.assertFalse(npu["runnable"])
        self.assertIn("Ollama-compatible NPU backend", npu["compatibility_reason"])

    def test_vendor_provider_states_merge_without_changing_legacy_backends(self):
        detector = AcceleratorDetector(
            device_names=lambda: ["Intel(R) AI Boost"],
            runtime_available=lambda provider: provider == "openvino",
            provider_devices=lambda provider: ["NPU"] if provider == "openvino" else [],
            windows_build=lambda: 26100,
            directx12_available=lambda: False,
            model_ready=lambda provider: provider == "openvino",
        )
        manager = HardwareBackendManager(
            self.root,
            command_available=lambda command: False,
            ai_device_detector=lambda: [],
            accelerator_detector=detector,
        )

        result = manager.detect()

        self.assertEqual(result[0]["id"], "cpu")
        openvino = next(item for item in result if item["id"] == "openvino")
        self.assertTrue(openvino["hardware_detected"])
        self.assertTrue(openvino["runtime_ready"])
        self.assertTrue(openvino["model_ready"])
        self.assertTrue(openvino["runnable"])

    def test_successful_probe_persists_preference_and_failure_quarantines_backend(self):
        manager = HardwareBackendManager(self.root, environment_writer=lambda name, value: None)

        manager.record_probe("cuda_v12", True)
        self.assertEqual(manager.status()["preferred_backend"], "cuda_v12")
        self.assertEqual(manager.status()["last_known_good"], "cuda_v12")

        manager.record_probe("cuda_v12", False, "runner crashed")
        status = HardwareBackendManager(self.root, environment_writer=lambda name, value: None).status()
        self.assertEqual(status["preferred_backend"], "cpu")
        self.assertIn("cuda_v12", status["quarantined"])
        self.assertEqual(status["last_error"], "runner crashed")

    def test_restore_cpu_clears_accelerator_preference_but_keeps_failure_history(self):
        writes = []
        manager = HardwareBackendManager(self.root, environment_writer=lambda name, value: writes.append((name, value)))
        manager.record_probe("cuda_v12", False, "failed")

        restored = manager.restore_cpu()

        self.assertEqual(restored["preferred_backend"], "cpu")
        self.assertIn("cuda_v12", restored["quarantined"])
        self.assertEqual(writes[-1], ("OLLAMA_LLM_LIBRARY", "cpu"))

    def test_runtime_failure_quarantines_only_an_active_accelerator(self):
        manager = HardwareBackendManager(
            self.root, environment_writer=lambda name, value: None, active_backend="cuda_v12"
        )
        manager.record_probe("cuda_v12", True)

        changed = manager.record_runtime_failure("request crashed")

        self.assertTrue(changed)
        self.assertEqual(manager.status()["preferred_backend"], "cpu")
        self.assertIn("cuda_v12", manager.status()["quarantined"])
        self.assertFalse(manager.record_runtime_failure("cpu request failed"))

        pending = HardwareBackendManager(self.root / "pending", environment_writer=lambda name, value: None)
        pending.record_probe("cuda_v12", True)
        self.assertFalse(pending.record_runtime_failure("still running on CPU"))

    def test_gpu_telemetry_returns_bounded_nvidia_metrics(self):
        manager = HardwareBackendManager(
            self.root,
            gpu_telemetry_reader=lambda: [{
                "index": 0,
                "name": "NVIDIA GeForce RTX 4060 Laptop GPU",
                "memory_total": 8188,
                "memory_used": 512,
                "memory_free": 7676,
                "utilization": 12,
                "temperature": 47,
            }],
        )

        self.assertEqual(manager.gpu_telemetry()[0]["memory_free"], 7676)
        self.assertEqual(manager.gpu_telemetry()[0]["index"], 0)


class HardwareGpuProbeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    async def asyncTearDown(self):
        self.temporary_directory.cleanup()

    async def test_ollama_gpu_probe_verifies_positive_offload_without_changing_runtime_library(self):
        writes = []

        async def probe(model):
            return {"gpu_percent": 100, "vram_bytes": 398_000_000, "evidence": "100% GPU"}

        manager = HardwareBackendManager(
            self.root,
            environment_writer=lambda name, value: writes.append((name, value)),
            gpu_telemetry_reader=lambda: [{"index": 0, "name": "RTX 4060"}],
            ollama_gpu_probe=probe,
        )

        result = await manager.probe("ollama_gpu", "qwen2.5-coder:0.5b")

        self.assertTrue(result["verified"])
        self.assertEqual(result["gpu_percent"], 100)
        self.assertEqual(result["vram_bytes"], 398_000_000)
        self.assertEqual(manager.status()["preferred_backend"], "ollama_gpu")
        self.assertEqual(writes, [])

    async def test_ollama_gpu_probe_rejects_zero_offload_and_preserves_cpu_fallback(self):
        async def probe(model):
            return {"gpu_percent": 0, "vram_bytes": 0, "evidence": "100% CPU"}

        manager = HardwareBackendManager(
            self.root,
            environment_writer=lambda name, value: None,
            gpu_telemetry_reader=lambda: [{"index": 0, "name": "RTX 4060"}],
            ollama_gpu_probe=probe,
        )

        result = await manager.probe("ollama_gpu", "qwen2.5-coder:0.5b")

        self.assertFalse(result["verified"])
        self.assertEqual(manager.status()["preferred_backend"], "cpu")
        self.assertIn("no GPU offload", result["error"])


class HardwareBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        runtime = self.root / "ollama"
        (runtime / "cuda_v12").mkdir(parents=True)
        self.calls = []

        async def runner(backend, model, prompts, repeats):
            self.calls.append((backend, model, tuple(prompts), repeats))
            if backend == "cuda_v12":
                return [
                    {"total_seconds": 0.5, "load_seconds": 0.1, "tokens": 20, "eval_seconds": 0.4}
                    for _ in range(len(prompts) * repeats)
                ]
            return [
                {"total_seconds": 1.0, "load_seconds": 0.2, "tokens": 20, "eval_seconds": 0.8}
                for _ in range(len(prompts) * repeats)
            ]

        self.manager = HardwareBackendManager(
            self.root,
            runtime_root=runtime,
            command_available=lambda command: command == "nvidia-smi",
            ai_device_detector=lambda: ["Intel(R) AI Boost"],
            environment_writer=lambda name, value: None,
            benchmark_runner=runner,
            gpu_telemetry_reader=lambda: [],
        )

    async def asyncTearDown(self):
        self.temporary_directory.cleanup()

    async def test_quick_benchmark_runs_cpu_first_with_identical_workload_and_relative_metrics(self):
        result = await self.manager.benchmark("quick", "qwen2.5-coder:0.5b")

        self.assertEqual([entry[0] for entry in self.calls], ["cpu", "cuda_v12"])
        self.assertEqual(self.calls[0][2:], self.calls[1][2:])
        self.assertEqual(self.calls[0][3], 1)
        self.assertEqual(len(self.calls[0][2]), 3)
        self.assertEqual([entry["backend"] for entry in result["results"]], ["cpu", "cuda_v12", "npu-0"])
        self.assertEqual(result["results"][0]["tokens_per_second"], 25.0)
        self.assertEqual(result["results"][1]["speedup_vs_cpu"], 2.0)
        self.assertEqual([sample["test"] for sample in result["results"][1]["tests"]], ["instruction", "reasoning", "code"])
        self.assertEqual(result["results"][1]["runtime"], "cuda_v12")
        self.assertEqual(result["results"][1]["kind"], "gpu")
        self.assertEqual(result["results"][2]["status"], "unavailable")
        self.assertEqual(self.manager.status()["preferred_backend"], "cpu")

    async def test_selected_accelerator_runs_with_cpu_baseline_and_rejects_unknown_target(self):
        result = await self.manager.benchmark("quick", "model", "cuda_v12")

        self.assertEqual([entry[0] for entry in self.calls], ["cpu", "cuda_v12"])
        self.assertEqual([entry["backend"] for entry in result["results"]], ["cpu", "cuda_v12"])
        self.assertEqual(result["target_backend"], "cuda_v12")

        with self.assertRaisesRegex(ValueError, "target"):
            await self.manager.benchmark("quick", "model", "unknown")

    async def test_thorough_benchmark_repeats_workload_and_persists_bounded_history(self):
        first = await self.manager.benchmark("thorough", "qwen2.5-coder:0.5b")

        self.assertEqual(self.calls[0][3], 3)
        self.assertEqual(self.manager.benchmark_history()[0]["id"], first["id"])

        for _ in range(22):
            await self.manager.benchmark("quick", "qwen2.5-coder:0.5b")

        history = HardwareBackendManager(
            self.root,
            command_available=lambda command: False,
            ai_device_detector=lambda: [],
            environment_writer=lambda name, value: None,
        ).benchmark_history()
        self.assertEqual(len(history), 20)
        self.assertEqual(history[0]["suite"], "quick")

    async def test_failed_backend_does_not_abort_later_results_or_create_invalid_speedup(self):
        async def failing_runner(backend, model, prompts, repeats):
            if backend == "cpu":
                raise RuntimeError("CPU runner failed")
            return [{"total_seconds": 0.5, "load_seconds": 0.1, "tokens": 10, "eval_seconds": 0.4}]

        self.manager.benchmark_runner = failing_runner
        result = await self.manager.benchmark("quick", "model")

        self.assertEqual(result["results"][0]["status"], "failed")
        self.assertEqual(result["results"][1]["status"], "completed")
        self.assertIsNone(result["results"][1]["speedup_vs_cpu"])

    async def test_rejects_invalid_suite_and_overlapping_run(self):
        with self.assertRaisesRegex(ValueError, "suite"):
            await self.manager.benchmark("overnight", "model")

        await self.manager._benchmark_lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "already running"):
                await self.manager.benchmark("quick", "model")
        finally:
            self.manager._benchmark_lock.release()

    async def test_legacy_history_is_normalized_for_current_result_renderer(self):
        legacy = [{
            "id": "old-run",
            "suite": "quick",
            "model": "model",
            "results": [{
                "backend": "cuda_v12", "name": "CUDA", "status": "completed",
                "tokens_per_second": 20.0, "average_total_seconds": 1.0,
                "average_load_seconds": 0.5, "speedup_vs_cpu": 2.0,
            }],
        }]
        self.manager.benchmark_path.write_text(json.dumps(legacy), encoding="utf-8")

        result = self.manager.benchmark_history()[0]["results"][0]

        self.assertEqual(result["runtime"], "cuda_v12")
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["tests"], [])
        self.assertFalse(result["active"])

    async def test_process_cleanup_ignores_process_that_already_exited(self):
        class ExitedProcess:
            returncode = 1

            def terminate(self):
                raise AssertionError("terminate must not be called")

        await self.manager._stop_process(ExitedProcess())


if __name__ == "__main__":
    unittest.main()
