from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import ollama

from web_app.inference.detection import AcceleratorDetector


class HardwareBackendManager:
    def __init__(
        self,
        data_root: Path,
        runtime_root: Path | None = None,
        command_available: Callable[[str], bool] | None = None,
        environment_writer: Callable[[str, str], None] | None = None,
        active_backend: str | None = None,
        ai_device_detector: Callable[[], list[str]] | None = None,
        benchmark_runner: Callable[[str, str, list[str], int], Awaitable[list[dict]]] | None = None,
        accelerator_detector: AcceleratorDetector | None = None,
        gpu_telemetry_reader: Callable[[], list[dict]] | None = None,
        ollama_gpu_probe: Callable[[str], Awaitable[dict]] | None = None,
        ollama_gpu_benchmark_runner: Callable[[str, str, list[str], int], Awaitable[list[dict]]] | None = None,
    ) -> None:
        self.path = Path(data_root).resolve() / "hardware-backend.json"
        self.benchmark_path = Path(data_root).resolve() / "hardware-benchmarks.json"
        self.runtime_root = runtime_root or Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "lib" / "ollama"
        self.command_available = command_available or (lambda command: shutil.which(command) is not None)
        self.environment_writer = environment_writer or self._write_user_environment
        self.active_backend = active_backend or os.environ.get("OLLAMA_LLM_LIBRARY", "cpu")
        self.ai_device_detector = ai_device_detector or self._detect_windows_ai_devices
        self.benchmark_runner = benchmark_runner or self._run_benchmark_backend
        self.accelerator_detector = accelerator_detector
        self.gpu_telemetry_reader = gpu_telemetry_reader or self._read_nvidia_telemetry
        self.ollama_gpu_probe = ollama_gpu_probe or self._probe_ollama_gpu
        self.ollama_gpu_benchmark_runner = ollama_gpu_benchmark_runner or self._run_ollama_gpu_benchmark
        self._benchmark_lock = asyncio.Lock()

    def gpu_telemetry(self) -> list[dict]:
        return self.gpu_telemetry_reader()

    @staticmethod
    async def _probe_ollama_gpu(model: str) -> dict:
        client = ollama.AsyncClient()
        await client.generate(
            model=model,
            prompt="Reply with exactly OK",
            stream=False,
            keep_alive="5m",
            options={"num_gpu": 999, "num_predict": 8},
        )
        response = await client.ps()
        payload = response.model_dump() if hasattr(response, "model_dump") else response
        running = next(
            (item for item in payload.get("models", []) if (item.get("model") or item.get("name")) == model),
            None,
        )
        if not running:
            return {"gpu_percent": 0, "vram_bytes": 0, "evidence": "Model was not reported by Ollama after the probe"}
        size = int(running.get("size") or 0)
        vram_bytes = int(running.get("size_vram") or 0)
        gpu_percent = round(vram_bytes * 100 / size) if size else 0
        return {
            "gpu_percent": gpu_percent,
            "vram_bytes": vram_bytes,
            "evidence": f"{gpu_percent}% GPU · {vram_bytes} VRAM bytes",
        }

    @staticmethod
    def _read_nvidia_telemetry() -> list[dict]:
        command = [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=5, check=False, creationflags=flags
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        gpus = []
        for line in result.stdout.splitlines():
            values = [value.strip() for value in line.split(",")]
            if len(values) != 7:
                continue
            try:
                gpus.append({
                    "index": int(values[0]),
                    "name": values[1],
                    "memory_total": int(values[2]),
                    "memory_used": int(values[3]),
                    "memory_free": int(values[4]),
                    "utilization": int(values[5]),
                    "temperature": int(values[6]),
                })
            except ValueError:
                continue
        return gpus

    def _read(self) -> dict:
        defaults = {"preferred_backend": "cpu", "last_known_good": "cpu", "quarantined": {}, "last_error": None}
        if not self.path.is_file():
            return defaults
        return {**defaults, **json.loads(self.path.read_text(encoding="utf-8"))}

    def _write(self, state: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".hardware-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        return state

    def status(self) -> dict:
        return {**self._read(), "active_backend": self.active_backend}

    def benchmark_history(self) -> list[dict]:
        if not self.benchmark_path.is_file():
            return []
        try:
            value = json.loads(self.benchmark_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(value, list):
            return []
        for benchmark in value:
            if not isinstance(benchmark, dict):
                continue
            benchmark.setdefault("target_backend", "all")
            benchmark.setdefault("created_at", "")
            for result in benchmark.get("results", []):
                if not isinstance(result, dict):
                    continue
                result.setdefault("runtime", result.get("backend", "unknown"))
                result.setdefault("kind", "unknown")
                result.setdefault("verified", False)
                result.setdefault("active", False)
                result.setdefault("tests", [])
        return value

    def _save_benchmark(self, benchmark: dict) -> None:
        history = [benchmark, *self.benchmark_history()][:20]
        self.benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.benchmark_path.parent / f".benchmarks-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(history, indent=2), encoding="utf-8")
        os.replace(temporary, self.benchmark_path)

    def detect(self) -> list[dict]:
        state = self._read()
        ready = {"hardware": True, "driver": True, "runtime": True, "model": True}
        result = [{
            "id": "cpu",
            "name": "CPU (compatible fallback)",
            "kind": "cpu",
            "runnable": True,
            "compatible": True,
            "verified": True,
            "readiness": ready,
        }]
        gpus = self.gpu_telemetry()
        if gpus:
            names = ", ".join(gpu["name"] for gpu in gpus)
            result.append({
                "id": "ollama_gpu",
                "name": f"Ollama GPU · {names}",
                "kind": "gpu",
                "runnable": True,
                "compatible": True,
                "verified": state["last_known_good"] == "ollama_gpu",
                "readiness": ready,
                "evidence": gpus,
            })
        candidates = []
        if self.command_available("nvidia-smi"):
            candidates.extend([
                ("cuda_v12", "NVIDIA CUDA 12"),
                ("cuda_v13", "NVIDIA CUDA 13"),
            ])
        if self.command_available("rocminfo"):
            candidates.append(("rocm_v7_1", "AMD ROCm 7.1"))
        if self.command_available("vulkaninfo"):
            candidates.append(("vulkan", "Vulkan"))
        for backend, name in candidates:
            runtime_ready = (self.runtime_root / backend).is_dir()
            result.append({
                "id": backend,
                "name": name,
                "kind": "gpu",
                "runnable": runtime_ready,
                "compatible": runtime_ready and backend not in state["quarantined"],
                "verified": state["last_known_good"] == backend,
                "quarantine_reason": state["quarantined"].get(backend),
                "compatibility_reason": None if runtime_ready else "Hardware tooling is detected, but this Ollama runtime is not installed.",
                "readiness": {**ready, "runtime": runtime_ready},
                "installation": None if runtime_ready else {
                    "kind": "runtime_guidance",
                    "automatic": False,
                    "guidance": "Update or reinstall Ollama with this runtime, then scan again; JSON_CODR will not modify display drivers.",
                },
            })
        for index, name in enumerate(self.ai_device_detector()):
            result.append({
                "id": f"npu-{index}",
                "name": name,
                "kind": "npu",
                "runnable": False,
                "compatible": False,
                "verified": False,
                "compatibility_reason": "Detected AI accelerator; no Ollama-compatible NPU backend is installed.",
                "readiness": {"hardware": True, "driver": True, "runtime": False, "model": False},
                "installation": {
                    "kind": "driver_guidance",
                    "automatic": False,
                    "guidance": "Install the device vendor's supported NPU driver and runtime, then scan again.",
                },
            })
        if self.accelerator_detector:
            for state_record in self.accelerator_detector.detect():
                state = state_record.model_dump(mode="json")
                installation = None
                if state["hardware_detected"] and not state["runtime_ready"]:
                    installation = {
                        "kind": "runtime",
                        "automatic": True,
                        "provider": state["provider"],
                        "includes_driver": False,
                        "guidance": "The isolated user-space runtime can be installed after approval; drivers are not included.",
                    }
                elif state["runtime_ready"] and not state["model_ready"]:
                    installation = {
                        "kind": "model_template",
                        "automatic": False,
                        "provider": state["provider"],
                        "guidance": "Select a compatible optimized model template from the provider catalog.",
                    }
                result.append({
                    "id": state["provider"],
                    "name": state["name"],
                    "kind": state["kind"],
                    "runnable": state["runtime_ready"] and state["model_ready"],
                    "compatible": state["runtime_ready"],
                    "verified": state["verified"],
                    "hardware_detected": state["hardware_detected"],
                    "runtime_ready": state["runtime_ready"],
                    "model_ready": state["model_ready"],
                    "evidence": state["evidence"],
                    "compatibility_reason": state["reason"],
                    "readiness": {
                        "hardware": state["hardware_detected"],
                        "driver": state["hardware_detected"],
                        "runtime": state["runtime_ready"],
                        "model": state["model_ready"],
                    },
                    "installation": installation,
                })
        return result

    def record_probe(self, backend: str, success: bool, error: str | None = None) -> dict:
        state = self._read()
        if success:
            state["preferred_backend"] = backend
            state["last_known_good"] = backend
            state["quarantined"].pop(backend, None)
            state["last_error"] = None
            if backend != "ollama_gpu":
                self.environment_writer("OLLAMA_LLM_LIBRARY", backend)
        else:
            state["preferred_backend"] = "cpu"
            state["quarantined"][backend] = error or "Probe failed"
            state["last_error"] = error or "Probe failed"
            if backend != "ollama_gpu":
                self.environment_writer("OLLAMA_LLM_LIBRARY", "cpu")
        return self._write(state)

    def restore_cpu(self) -> dict:
        state = self._read()
        state["preferred_backend"] = "cpu"
        state["last_known_good"] = "cpu"
        self.environment_writer("OLLAMA_LLM_LIBRARY", "cpu")
        return self._write(state)

    def record_runtime_failure(self, error: str) -> bool:
        backend = self.active_backend
        if backend == "cpu":
            return False
        self.record_probe(backend, False, error)
        self.active_backend = "cpu"
        return True

    async def probe(self, backend: str, model: str) -> dict:
        available = {item["id"] for item in self.detect()}
        if backend not in available:
            raise ValueError("Backend is not available on this machine")
        if backend == "ollama_gpu":
            try:
                evidence = await asyncio.wait_for(self.ollama_gpu_probe(model), timeout=120)
                verified = int(evidence.get("gpu_percent") or 0) > 0 and int(evidence.get("vram_bytes") or 0) > 0
                error = None if verified else "Ollama completed the test but reported no GPU offload"
            except Exception as exception:
                evidence = {"gpu_percent": 0, "vram_bytes": 0, "evidence": str(exception)}
                verified = False
                error = f"Ollama GPU probe failed: {exception}"
            state = self.record_probe(backend, verified, error)
            return {
                **state,
                **evidence,
                "verified": verified,
                "error": error,
                "restart_required": False,
            }
        executable = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
        environment = os.environ.copy()
        environment.update({"OLLAMA_HOST": "127.0.0.1:11435", "OLLAMA_LLM_LIBRARY": backend})
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(executable, "serve", env=environment, creationflags=flags)
        client = ollama.AsyncClient(host="http://127.0.0.1:11435")
        try:
            for _ in range(30):
                try:
                    await asyncio.wait_for(client.list(), timeout=2)
                    break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                raise RuntimeError("Isolated Ollama probe did not start")
            response = await asyncio.wait_for(client.generate(model=model, prompt="Reply with exactly OK", stream=False, keep_alive=0), timeout=120)
            text = response.response if hasattr(response, "response") else response.get("response", "")
            if not text.strip():
                raise RuntimeError("Backend returned an empty response")
        except Exception as error:
            return {**self.record_probe(backend, False, str(error)), "restart_required": False}
        finally:
            await self._stop_process(process)
        return {**self.record_probe(backend, True), "restart_required": backend != os.environ.get("OLLAMA_LLM_LIBRARY", "cpu")}

    async def benchmark(self, suite: str, model: str, backend: str = "all") -> dict:
        if suite not in {"quick", "thorough"}:
            raise ValueError("Benchmark suite must be quick or thorough")
        if self._benchmark_lock.locked():
            raise RuntimeError("A hardware benchmark is already running")
        prompts = [
            "Reply with exactly: JSON_CODR benchmark ready.",
            "Return only the sum of the integers from 1 through 100.",
            "Write a compact Python function named clamp that bounds a number between a minimum and maximum.",
        ]
        repeats = 1 if suite == "quick" else 3
        async with self._benchmark_lock:
            detected = self.detect()
            detected_ids = {candidate["id"] for candidate in detected}
            if backend != "all" and backend not in detected_ids:
                raise ValueError("Benchmark target is not detected on this machine")
            selected = detected if backend == "all" else [
                candidate for candidate in detected if candidate["id"] == "cpu" or candidate["id"] == backend
            ]
            results = []
            test_names = ["instruction", "reasoning", "code"]
            for candidate in selected:
                if not candidate["runnable"] or not candidate["compatible"]:
                    results.append({
                        "backend": candidate["id"],
                        "name": candidate["name"],
                        "runtime": candidate["id"],
                        "kind": candidate["kind"],
                        "verified": candidate["verified"],
                        "active": candidate["id"] == self.active_backend,
                        "status": "unavailable",
                        "error": candidate.get("compatibility_reason") or candidate.get("quarantine_reason"),
                        "speedup_vs_cpu": None,
                    })
                    continue
                try:
                    runner = self.ollama_gpu_benchmark_runner if candidate["id"] == "ollama_gpu" else self.benchmark_runner
                    samples = await runner(candidate["id"], model, prompts, repeats)
                    total_tokens = sum(sample["tokens"] for sample in samples)
                    eval_seconds = sum(sample["eval_seconds"] for sample in samples)
                    tests = [{
                        "test": test_names[index % len(test_names)],
                        "repetition": index // len(test_names) + 1,
                        "total_seconds": round(sample["total_seconds"], 3),
                        "load_seconds": round(sample["load_seconds"], 3),
                        "tokens": sample["tokens"],
                        "tokens_per_second": round(sample["tokens"] / sample["eval_seconds"], 3) if sample["eval_seconds"] else 0.0,
                    } for index, sample in enumerate(samples)]
                    results.append({
                        "backend": candidate["id"],
                        "name": candidate["name"],
                        "runtime": candidate["id"],
                        "kind": candidate["kind"],
                        "verified": candidate["verified"],
                        "active": candidate["id"] == self.active_backend,
                        "status": "completed",
                        "samples": len(samples),
                        "tests": tests,
                        "average_total_seconds": round(sum(sample["total_seconds"] for sample in samples) / len(samples), 3),
                        "average_load_seconds": round(sum(sample["load_seconds"] for sample in samples) / len(samples), 3),
                        "tokens_per_second": round(total_tokens / eval_seconds, 3) if eval_seconds else 0.0,
                        "gpu_percent": max((int(sample.get("gpu_percent") or 0) for sample in samples), default=0),
                        "vram_bytes": max((int(sample.get("vram_bytes") or 0) for sample in samples), default=0),
                        "speedup_vs_cpu": None,
                    })
                except Exception as error:
                    results.append({
                        "backend": candidate["id"],
                        "name": candidate["name"],
                        "runtime": candidate["id"],
                        "kind": candidate["kind"],
                        "verified": candidate["verified"],
                        "active": candidate["id"] == self.active_backend,
                        "status": "failed",
                        "error": str(error),
                        "speedup_vs_cpu": None,
                    })
            cpu = next((item for item in results if item["backend"] == "cpu" and item["status"] == "completed"), None)
            if cpu and cpu["tokens_per_second"]:
                for result in results:
                    if result["status"] == "completed":
                        result["speedup_vs_cpu"] = round(result["tokens_per_second"] / cpu["tokens_per_second"], 3)
            benchmark = {
                "id": uuid.uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "suite": suite,
                "model": model,
                "target_backend": backend,
                "prompt_count": len(prompts),
                "repeats": repeats,
                "results": results,
            }
            self._save_benchmark(benchmark)
            return benchmark

    @staticmethod
    async def _run_ollama_gpu_benchmark(backend: str, model: str, prompts: list[str], repeats: int) -> list[dict]:
        client = ollama.AsyncClient()
        options = {"temperature": 0, "num_predict": 96, "num_gpu": 999}
        await asyncio.wait_for(
            client.generate(model=model, prompt=prompts[0], options=options, stream=False, keep_alive="5m"),
            timeout=120,
        )
        samples = []
        for _ in range(repeats):
            for prompt in prompts:
                started = time.perf_counter()
                response = await asyncio.wait_for(
                    client.generate(model=model, prompt=prompt, options=options, stream=False, keep_alive="5m"),
                    timeout=120,
                )
                samples.append({
                    "total_seconds": time.perf_counter() - started,
                    "load_seconds": getattr(response, "load_duration", 0) / 1_000_000_000,
                    "tokens": getattr(response, "eval_count", 0) or 0,
                    "eval_seconds": getattr(response, "eval_duration", 0) / 1_000_000_000,
                })
        runtime = await client.ps()
        payload = runtime.model_dump() if hasattr(runtime, "model_dump") else runtime
        running = next(
            (item for item in payload.get("models", []) if (item.get("model") or item.get("name")) == model),
            None,
        )
        size = int((running or {}).get("size") or 0)
        vram_bytes = int((running or {}).get("size_vram") or 0)
        gpu_percent = round(vram_bytes * 100 / size) if size else 0
        if gpu_percent <= 0 or vram_bytes <= 0:
            raise RuntimeError("Ollama benchmark reported no GPU offload")
        for sample in samples:
            sample.update({"gpu_percent": gpu_percent, "vram_bytes": vram_bytes})
        return samples

    async def _run_benchmark_backend(self, backend: str, model: str, prompts: list[str], repeats: int) -> list[dict]:
        executable = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
        environment = os.environ.copy()
        environment.update({"OLLAMA_HOST": "127.0.0.1:11435", "OLLAMA_LLM_LIBRARY": backend})
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(executable, "serve", env=environment, creationflags=flags)
        client = ollama.AsyncClient(host="http://127.0.0.1:11435")
        try:
            for _ in range(30):
                try:
                    await asyncio.wait_for(client.list(), timeout=2)
                    break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                raise RuntimeError("Isolated benchmark Ollama did not start")
            options = {"temperature": 0, "num_predict": 96}
            await asyncio.wait_for(client.generate(model=model, prompt=prompts[0], options=options, stream=False, keep_alive=0), timeout=120)
            samples = []
            for _ in range(repeats):
                for prompt in prompts:
                    started = time.perf_counter()
                    response = await asyncio.wait_for(
                        client.generate(model=model, prompt=prompt, options=options, stream=False, keep_alive=0),
                        timeout=120,
                    )
                    total_seconds = time.perf_counter() - started
                    samples.append({
                        "total_seconds": total_seconds,
                        "load_seconds": getattr(response, "load_duration", 0) / 1_000_000_000,
                        "tokens": getattr(response, "eval_count", 0) or 0,
                        "eval_seconds": getattr(response, "eval_duration", 0) / 1_000_000_000,
                    })
            return samples
        finally:
            await self._stop_process(process)

    @staticmethod
    async def _stop_process(process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    @staticmethod
    def _write_user_environment(name: str, value: str) -> None:
        if os.name != "nt":
            return
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    @staticmethod
    def _detect_windows_ai_devices() -> list[str]:
        if os.name != "nt":
            return []
        command = [
            "powershell.exe", "-NoProfile", "-Command",
            "Get-CimInstance Win32_PnPEntity | Select-Object -ExpandProperty Name",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return []
        return list(dict.fromkeys(
            line.strip() for line in result.stdout.splitlines()
            if HardwareBackendManager.is_ai_device_name(line.strip())
        ))

    @staticmethod
    def is_ai_device_name(name: str) -> bool:
        return bool(re.search(
            r"(?i)(?:\bNPU\b|neural (?:processing unit|processor)|intel(?:\(r\))? AI Boost|AMD Ryzen AI|Qualcomm Hexagon)",
            name,
        ))
