from __future__ import annotations

from web_app.inference.contracts import ProviderKind
from web_app.inference.providers.onnx_genai import OnnxGenAIProvider
from web_app.inference.providers.openvino import OpenVINOProvider


class ProviderRegistry:
    def __init__(self, clients: dict[ProviderKind, object], model_root=None) -> None:
        self._providers = {}
        for kind, client in clients.items():
            self._providers[kind] = OpenVINOProvider(client, model_root) if kind is ProviderKind.openvino else OnnxGenAIProvider(kind, client, model_root)

    def get(self, provider: ProviderKind):
        try:
            return self._providers[provider]
        except KeyError as error:
            raise ValueError(f"Provider {provider.value} is unavailable") from error

    def available(self) -> tuple[ProviderKind, ...]:
        return tuple(self._providers)
