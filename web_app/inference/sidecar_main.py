from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _openvino_handler(operation: str, payload: dict) -> dict:
    import openvino_genai
    if operation == "health":
        return {"status": "ready"}
    model_path = Path(payload["repository"])
    if not model_path.is_dir():
        raise RuntimeError(f"Optimized model artifact is not installed: {model_path}")
    pipeline = openvino_genai.LLMPipeline(str(model_path), payload.get("device", "NPU"))
    if operation == "chat":
        text = pipeline.generate(payload["prompt"], max_new_tokens=int(payload.get("max_new_tokens", 512)))
        return _chat_result(payload["model_id"], str(text))
    if operation == "benchmark":
        return {"samples": _benchmark(lambda prompt: pipeline.generate(prompt, max_new_tokens=96), payload)}
    raise RuntimeError("Unsupported connector operation")


def _onnx_handler(operation: str, payload: dict) -> dict:
    import onnxruntime_genai as og
    if operation == "health":
        return {"status": "ready"}
    model_path = Path(payload["repository"])
    if not model_path.is_dir():
        raise RuntimeError(f"Optimized model artifact is not installed: {model_path}")
    model = og.Model(str(model_path))
    tokenizer = og.Tokenizer(model)

    def generate(prompt: str) -> str:
        params = og.GeneratorParams(model)
        params.set_search_options(max_length=512)
        generator = og.Generator(model, params)
        generator.append_tokens(tokenizer.encode(prompt))
        while not generator.is_done():
            generator.generate_next_token()
        return tokenizer.decode(generator.get_sequence(0))

    if operation == "chat":
        return _chat_result(payload["model_id"], generate(payload["prompt"]))
    if operation == "benchmark":
        return {"samples": _benchmark(generate, payload)}
    raise RuntimeError("Unsupported connector operation")


def _chat_result(model_id: str, text: str) -> dict:
    try:
        parsed = json.loads(text)
        if all(key in parsed for key in ("status", "summary", "content")):
            return {"model": model_id, **parsed}
    except json.JSONDecodeError:
        pass
    return {"model": model_id, "status": "success", "summary": "Optimized connector response", "content": text}


def _benchmark(generate, payload: dict) -> list[dict]:
    samples = []
    for _ in range(int(payload.get("repeats", 1))):
        for prompt in payload.get("prompts", []):
            started = time.perf_counter()
            text = str(generate(prompt))
            seconds = time.perf_counter() - started
            tokens = max(1, len(text.split()))
            samples.append({"total_seconds": seconds, "load_seconds": 0.0, "tokens": tokens, "eval_seconds": seconds})
    return samples


def handle_request(request: dict, handlers: dict | None = None) -> dict:
    operation = request.get("operation")
    payload = request.get("payload") or {}
    provider = payload.get("provider")
    handlers = handlers or {
        "openvino": _openvino_handler,
        "ryzen_ai": _onnx_handler,
        "automatic": _onnx_handler,
        "DML": _onnx_handler,
    }
    try:
        if operation == "health" and not provider:
            return {"ok": True, "result": {"status": "ready"}}
        handler = handlers.get(provider)
        if not handler:
            raise RuntimeError("Unsupported connector provider")
        return {"ok": True, "result": handler(operation, payload)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def main() -> int:
    try:
        request = json.loads(sys.stdin.readline())
        response = handle_request(request)
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    sys.stdout.write(json.dumps(response) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
