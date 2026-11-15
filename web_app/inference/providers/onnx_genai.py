from __future__ import annotations

from web_app.inference.contracts import ProviderKind
from web_app.inference.providers.openvino import OpenVINOProvider


class OnnxGenAIProvider(OpenVINOProvider):
    def __init__(self, kind: ProviderKind, client) -> None:
        if kind not in {ProviderKind.ryzen_ai, ProviderKind.winml, ProviderKind.directml}:
            raise ValueError("Unsupported ONNX Runtime GenAI provider")
        self.kind = kind
        super().__init__(client)

    def _payload(self, model):
        if model.provider is not self.kind:
            raise ValueError("Model is not compatible with this provider")
        execution_provider = {
            ProviderKind.ryzen_ai: "ryzen_ai",
            ProviderKind.winml: "automatic",
            ProviderKind.directml: "DML",
        }[self.kind]
        return {
            "provider": execution_provider,
            "model_id": model.id,
            "repository": model.repository,
            "device": model.device,
        }
