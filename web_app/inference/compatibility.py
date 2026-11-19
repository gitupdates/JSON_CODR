from __future__ import annotations

from web_app.inference.contracts import OptimizedModelRecord


def ollama_model_status(model: str, backend: str, running: list[dict], compatible: bool) -> dict:
    active = next((item for item in running if item.get("name") == model), None)
    vram = int((active or {}).get("size_vram") or 0)
    if backend == "cpu":
        return {"model": model, "status": "runnable" if compatible else "unsupported", "evidence": {"execution": "CPU"}}
    if not compatible:
        return {"model": model, "status": "unsupported", "reason": "Backend is unavailable", "evidence": {}}
    if vram > 0:
        return {"model": model, "status": "accelerated", "evidence": {"vram_bytes": vram, "processor": active.get("processor")}}
    return {"model": model, "status": "runnable", "reason": "GPU acceleration is not verified for this model", "evidence": {"vram_bytes": 0}}


def optimized_model_status(model: OptimizedModelRecord, installed: bool, runtime_ready: bool, verified: bool) -> dict:
    if verified:
        status = "accelerated"
    elif installed and runtime_ready:
        status = "runnable"
    elif installed:
        status = "installed"
    else:
        status = "candidate"
    return {
        "model": model.id, "provider": model.provider.value, "device": model.device,
        "format": model.format, "status": status, "installed": installed,
        "source_url": model.source_url, "revision": model.revision, "license": model.license,
        "evidence": {"runtime_ready": runtime_ready, "probe_verified": verified},
    }
