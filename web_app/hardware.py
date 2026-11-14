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
    ) -> None:
        self.path = Path(data_root).resolve() / "hardware-backend.json"
        self.benchmark_path = Path(data_root).resolve() / "hardware-benchmarks.json"
        self.runtime_root = runtime_root or Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "lib" / "ollama"
        self.command_available = command_available or (lambda command: shutil.which(command) is not None)
        self.environment_writer = environment_writer or self._write_user_environment
        self.active_backend = active_backend or os.environ.get("OLLAMA_LLM_LIBRARY", "cpu")
        self.ai_device_detector = ai_device_detector or self._detect_windows_ai_devices
        self.benchmark_runner = benchmark_runner or self._run_benchmark_backend
        self._benchmark_lock = asyncio.Lock()

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
        return value if isinstance(value, list) else []

    def _save_benchmark(self, benchmark: dict) -> None:
        history = [benchmark, *self.benchmark_history()][:20]
        self.benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.benchmark_path.parent / f".benchmarks-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(history, indent=2), encoding="utf-8")
        os.replace(temporary, self.benchmark_path)

    def detect(self) -> list[dict]:
        state = self._read()
        result = [{"id": "cpu", "name": "CPU (compatible fallback)", "kind": "cpu", "runnable": True, "compatible": True, "verified": True}]
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
            if (self.runtime_root / backend).is_dir():
                result.append({
                    "id": backend,
                    "name": name,
                    "kind": "gpu",
                    "runnable": True,
                    "compatible": backend not in state["quarantined"],
                    "verified": state["last_known_good"] == backend,
                    "quarantine_reason": state["quarantined"].get(backend),
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
            })
        return result

    def record_probe(self, backend: str, success: bool, error: str | None = None) -> dict:
        state = self._read()
        if success:
            state["preferred_backend"] = backend
            state["last_known_good"] = backend
            state["quarantined"].pop(backend, None)
            state["last_error"] = None
            self.environment_writer("OLLAMA_LLM_LIBRARY", backend)
        else:
            state["preferred_backend"] = "cpu"
            state["quarantined"][backend] = error or "Probe failed"
            state["last_error"] = error or "Probe failed"
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
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        return {**self.record_probe(backend, True), "restart_required": backend != os.environ.get("OLLAMA_LLM_LIBRARY", "cpu")}

    async def benchmark(self, suite: str, model: str) -> dict:
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
            results = []
            for candidate in detected:
                if not candidate["runnable"] or not candidate["compatible"]:
                    results.append({
                        "backend": candidate["id"],
                        "name": candidate["name"],
                        "status": "unavailable",
                        "error": candidate.get("compatibility_reason") or candidate.get("quarantine_reason"),
                        "speedup_vs_cpu": None,
                    })
                    continue
                try:
                    samples = await self.benchmark_runner(candidate["id"], model, prompts, repeats)
                    total_tokens = sum(sample["tokens"] for sample in samples)
                    eval_seconds = sum(sample["eval_seconds"] for sample in samples)
                    results.append({
                        "backend": candidate["id"],
                        "name": candidate["name"],
                        "status": "completed",
                        "samples": len(samples),
                        "average_total_seconds": round(sum(sample["total_seconds"] for sample in samples) / len(samples), 3),
                        "average_load_seconds": round(sum(sample["load_seconds"] for sample in samples) / len(samples), 3),
                        "tokens_per_second": round(total_tokens / eval_seconds, 3) if eval_seconds else 0.0,
                        "speedup_vs_cpu": None,
                    })
                except Exception as error:
                    results.append({
                        "backend": candidate["id"],
                        "name": candidate["name"],
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
                "prompt_count": len(prompts),
                "repeats": repeats,
                "results": results,
            }
            self._save_benchmark(benchmark)
            return benchmark

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
            if process.returncode is None:
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
