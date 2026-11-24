from __future__ import annotations

from typing import Any

from web_app.inference.contracts import OptimizedModelRecord, ProbeResult, ProviderKind
from web_app.models import ChatResult


class OpenVINOProvider:
    kind = ProviderKind.openvino

    def __init__(self, client, model_root=None) -> None:
        self.client = client
        self.model_root = model_root

    def _payload(self, model: OptimizedModelRecord) -> dict:
        if model.provider is not self.kind or model.device not in {"CPU", "GPU", "NPU"}:
            raise ValueError("Model is not compatible with this provider")
        repository = self.model_root / self.kind.value / model.repository.replace("/", "--") if self.model_root else model.repository
        return {"provider": self.kind.value, "model_id": model.id, "repository": str(repository), "device": model.device}

    async def health(self) -> dict[str, Any]:
        return await self.client.request("health", {"provider": self.kind.value})

    async def list_models(self) -> list[OptimizedModelRecord]:
        return []

    async def probe(self, model: OptimizedModelRecord) -> ProbeResult:
        try:
            response = await self.chat(model, "Reply with exactly OK", max_new_tokens=8)
            return ProbeResult(model_id=model.id, provider=self.kind, success=True, response=response)
        except Exception as error:
            return ProbeResult(model_id=model.id, provider=self.kind, success=False, error=str(error))

    async def chat(self, model: OptimizedModelRecord, prompt: str, images=None, max_new_tokens: int = 512) -> ChatResult:
        result = await self.client.request("chat", {
            **self._payload(model), "prompt": prompt, "images": images or [], "max_new_tokens": max_new_tokens,
        })
        return ChatResult.model_validate(result)

    async def benchmark(self, model: OptimizedModelRecord, prompts: list[str], repeats: int) -> list[dict]:
        result = await self.client.request("benchmark", {**self._payload(model), "prompts": prompts, "repeats": repeats})
        return result.get("samples", [])
