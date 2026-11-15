from __future__ import annotations

from typing import Any

from web_app.inference.contracts import OptimizedModelRecord, ProbeResult, ProviderKind
from web_app.models import ChatResult


class OpenVINOProvider:
    kind = ProviderKind.openvino

    def __init__(self, client) -> None:
        self.client = client

    def _payload(self, model: OptimizedModelRecord) -> dict:
        if model.provider is not self.kind or model.device not in {"CPU", "GPU", "NPU"}:
            raise ValueError("Model is not compatible with this provider")
        return {"provider": self.kind.value, "model_id": model.id, "repository": model.repository, "device": model.device}

    async def health(self) -> dict[str, Any]:
        return await self.client.request("health", {"provider": self.kind.value})

    async def list_models(self) -> list[OptimizedModelRecord]:
        return []

    async def probe(self, model: OptimizedModelRecord) -> ProbeResult:
        try:
            response = await self.chat(model, "Reply with exactly OK")
            return ProbeResult(model_id=model.id, provider=self.kind, success=True, response=response)
        except Exception as error:
            return ProbeResult(model_id=model.id, provider=self.kind, success=False, error=str(error))

    async def chat(self, model: OptimizedModelRecord, prompt: str, images=None) -> ChatResult:
        result = await self.client.request("chat", {**self._payload(model), "prompt": prompt, "images": images or []})
        return ChatResult.model_validate(result)

    async def benchmark(self, model: OptimizedModelRecord, prompts: list[str], repeats: int) -> list[dict]:
        result = await self.client.request("benchmark", {**self._payload(model), "prompts": prompts, "repeats": repeats})
        return result.get("samples", [])
