from __future__ import annotations

from web_app.inference.catalog import OptimizedModelCatalog


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

    async def probe(self, model_id: str):
        model = self.catalog.get(model_id)
        result = await self.registry.get(model.provider).probe(model)
        if result.success:
            self.verified_models.add(model_id)
            self.quarantined.pop(model_id, None)
        else:
            self.quarantined[model_id] = result.error or "Probe failed"
        return result

    async def chat(self, model_id: str, prompt: str, images=None):
        try:
            model = self.catalog.get(model_id)
        except KeyError:
            return await self.ollama.chat(model_id, prompt, images=images)
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
            result = await self.ollama.chat(fallback, prompt, images=images)
            result.summary = f"Fallback to {fallback} after {model.provider.value} failure: {result.summary}"
            return result
