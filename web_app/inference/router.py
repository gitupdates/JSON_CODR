from __future__ import annotations

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.protocol import InferenceRequest


class InferenceRouter:
    def __init__(self, ollama, catalog: OptimizedModelCatalog, registry, verified_models: set[str] | None = None) -> None:
        self.ollama = ollama
        self.catalog = catalog
        self.registry = registry
        self.verified_models = verified_models or set()
        self.quarantined: dict[str, str] = {}

    async def list_models(self) -> list[dict]:
        result = await self.ollama.list_models()
        for model in self.catalog.list():
            result.append({
                "name": model.id,
                "installed": model.id in self.verified_models and model.id not in self.quarantined,
                "provider": model.provider.value,
                "device": model.device,
                "optimized": True,
                "fallback": model.ollama_fallback,
            })
        return result

    async def supports_vision(self, model_id: str) -> bool:
        try:
            self.catalog.get(model_id)
        except KeyError:
            return await self.ollama.supports_vision(model_id)
        return False

    async def generate(self, request: InferenceRequest):
        try:
            self.catalog.get(request.model)
        except KeyError:
            generate = getattr(self.ollama, "generate", None)
            if callable(generate):
                async for event in generate(request):
                    yield event
                return
            raise ValueError("Native provider does not support canonical inference")
        raise ValueError("Optimized providers do not yet support canonical inference")

    async def probe(self, model_id: str):
        model = self.catalog.get(model_id)
        result = await self.registry.get(model.provider).probe(model)
        if result.success:
            self.verified_models.add(model_id)
            self.quarantined.pop(model_id, None)
        else:
            self.quarantined[model_id] = result.error or "Probe failed"
        return result

    async def chat(self, model_id: str, prompt: str, images=None, allow_repair: bool = True):
        try:
            model = self.catalog.get(model_id)
        except KeyError:
            return await self.ollama.chat(model_id, prompt, images=images, allow_repair=allow_repair)
        if model_id not in self.verified_models or model_id in self.quarantined:
            raise ValueError("Optimized model is not verified")
        try:
            return await self.registry.get(model.provider).chat(model, prompt, images=images)
        except Exception as error:
            self.quarantined[model_id] = str(error)
            installed = [item["name"] for item in await self.ollama.list_models() if item.get("installed")]
            fallback = model.ollama_fallback if model.ollama_fallback in installed else (installed[0] if installed else None)
            if not fallback:
                raise
            result = await self.ollama.chat(fallback, prompt, images=images, allow_repair=allow_repair)
            result.summary = f"Fallback to {fallback} after {model.provider.value} failure: {result.summary}"
            result.provider_events.insert(0, {
                "type": "provider_fallback",
                "requested_model": model_id,
                "failed_provider": model.provider.value,
                "error": f"{type(error).__name__}: {error}",
                "effective_model": fallback,
            })
            return result

    async def stream_chat(self, model_id: str, prompt: str, images=None, public_reasoning: bool = False):
        try:
            model = self.catalog.get(model_id)
        except KeyError:
            async for event in self.ollama.stream_chat(
                model_id,
                prompt,
                images=images,
                public_reasoning=public_reasoning,
            ):
                yield event
            return
        if model_id not in self.verified_models or model_id in self.quarantined:
            raise ValueError("Optimized model is not verified")
        provider = self.registry.get(model.provider)
        try:
            stream_chat = getattr(provider, "stream_chat", None)
            if callable(stream_chat):
                async for event in stream_chat(
                    model,
                    prompt,
                    images=images,
                    public_reasoning=public_reasoning,
                ):
                    yield event
                return
            result = await provider.chat(model, prompt, images=images)
            yield {"type": "completed", "result": result}
        except Exception as error:
            self.quarantined[model_id] = str(error)
            installed = [item["name"] for item in await self.ollama.list_models() if item.get("installed")]
            fallback = model.ollama_fallback if model.ollama_fallback in installed else (installed[0] if installed else None)
            if not fallback:
                raise
            async for event in self.ollama.stream_chat(
                fallback,
                prompt,
                images=images,
                public_reasoning=public_reasoning,
            ):
                if event.get("type") == "completed":
                    result = event.get("result")
                    if result is not None:
                        result.summary = f"Fallback to {fallback} after {model.provider.value} failure: {result.summary}"
                yield event
