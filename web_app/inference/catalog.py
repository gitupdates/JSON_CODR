from __future__ import annotations

from collections.abc import Iterable

from web_app.inference.contracts import OptimizedModelRecord, ProviderKind


INITIAL_MODELS = (
    OptimizedModelRecord(
        id="openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-fp16-ov",
        provider=ProviderKind.openvino,
        repository="OpenVINO/Qwen2.5-Coder-1.5B-Instruct-fp16-ov",
        source_url="https://huggingface.co/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-fp16-ov",
        revision="b69e4f7d93d76dd84dc6bdbee19be5470fd07088",
        license="apache-2.0",
        device="NPU",
        format="openvino_ir",
        requirements=("openvino-genai>=2025.2", "openvino-tokenizers>=2025.2"),
        ollama_fallback="qwen2.5-coder:1.5b",
    ),
    OptimizedModelRecord(
        id="ryzen_ai/amd/Qwen2.5-Coder-0.5B-Instruct_rai_1.8.0_m1.0_npu",
        provider=ProviderKind.ryzen_ai,
        repository="amd/Qwen2.5-Coder-0.5B-Instruct_rai_1.8.0_m1.0_npu",
        source_url="https://huggingface.co/amd/Qwen2.5-Coder-0.5B-Instruct_rai_1.8.0_m1.0_npu",
        revision="72a45861f98aad6aedcf6b0d283bae20c979b92e",
        license="apache-2.0",
        device="NPU",
        format="onnx_genai",
        requirements=("ryzen-ai-software>=1.8", "onnxruntime-genai"),
        ollama_fallback="qwen2.5-coder:0.5b",
        context_length=4096,
    ),
)


class OptimizedModelCatalog:
    def __init__(self, models: Iterable[OptimizedModelRecord] | None = None) -> None:
        records = tuple(INITIAL_MODELS if models is None else models)
        identifiers = [model.id for model in records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Catalog contains duplicate model ids")
        for model in records:
            if not model.id.startswith(f"{model.provider.value}/") or model.id.count("/") < 2:
                raise ValueError("Optimized model id must be provider-qualified")
        self._models = records

    def list(self) -> tuple[OptimizedModelRecord, ...]:
        return self._models

    def get(self, model_id: str) -> OptimizedModelRecord:
        for model in self._models:
            if model.id == model_id:
                return model
        raise KeyError(model_id)
