from __future__ import annotations

from collections.abc import Iterable

from web_app.inference.contracts import OptimizedArtifactRecord, OptimizedModelRecord, ProviderKind


INITIAL_MODELS = (
    OptimizedModelRecord(
        id="openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov",
        provider=ProviderKind.openvino,
        repository="OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov",
        source_url="https://huggingface.co/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov",
        revision="3727da92d6202a996e555911c9725afd7ea54c4a",
        license="apache-2.0",
        device="NPU",
        format="openvino_ir",
        requirements=("openvino-genai==2025.4", "openvino-tokenizers==2025.4"),
        ollama_fallback="qwen2.5-coder:1.5b",
        maximum_download_bytes=1_100_000_000,
        artifacts=(
            OptimizedArtifactRecord(path="added_tokens.json", size=605, sha256="58b54bbe36fc752f79a24a271ef66a0a0830054b4dfad94bde757d851968060b"),
            OptimizedArtifactRecord(path="config.json", size=723, sha256="3b18adf8077f45bbb63e3760ed65b899db18dd6215c5801f312f7cb5cfed1a6c"),
            OptimizedArtifactRecord(path="generation_config.json", size=242, sha256="a74797aba705d511c09cc4d12c4517653426ac5559841f0bad62aa8733e100da"),
            OptimizedArtifactRecord(path="merges.txt", size=1_671_853, sha256="8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5"),
            OptimizedArtifactRecord(path="openvino_detokenizer.bin", size=2_189_639, sha256="3ca47601554a3b871c1e45e8f31aa6e17d726365c075fb430d1a2089484ae8d6"),
            OptimizedArtifactRecord(path="openvino_detokenizer.xml", size=9_610, sha256="4009f2854ef15dbc382349781fbcd69b51417a70be9587d9e7e15d139976df3d"),
            OptimizedArtifactRecord(path="openvino_model.bin", size=914_982_600, sha256="adfb49e918b546bce8066f3792447589a16497e100100359d4a668954b1e1a42"),
            OptimizedArtifactRecord(path="openvino_model.xml", size=2_727_089, sha256="7a92eaf9da4f4567155350a253e0683a752f700f0be4d350bfb13ab10e7331c4"),
            OptimizedArtifactRecord(path="openvino_tokenizer.bin", size=5_588_645, sha256="6e3a56216ade1ed29c7744b5e6bc27ffdc85038747766e838b3d881713fc0633"),
            OptimizedArtifactRecord(path="openvino_tokenizer.xml", size=25_262, sha256="5aec04982d9a4503cd945646c9c486946ec3195716f701b6ea00f2723084c59e"),
            OptimizedArtifactRecord(path="special_tokens_map.json", size=613, sha256="76862e765266b85aa9459767e33cbaf13970f327a0e88d1c65846c2ddd3a1ecd"),
            OptimizedArtifactRecord(path="tokenizer.json", size=11_421_896, sha256="9c5ae00e602b8860cbd784ba82a8aa14e8feecec692e7076590d014d7b7fdafa"),
            OptimizedArtifactRecord(path="tokenizer_config.json", size=7_335, sha256="74ecb08f77f4d27fdc01b86c03038bf0102b1395c28f2016334af062ce1ec5be"),
            OptimizedArtifactRecord(path="vocab.json", size=2_776_833, sha256="ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
        ),
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
