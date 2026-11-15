from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

from web_app.inference.catalog import OptimizedModelCatalog

APPROVED_PROVIDERS = {"openvino", "ryzen_ai", "winml", "directml"}
APPROVED_LICENSES = {"apache-2.0", "mit", "bsd-3-clause", "openrail", "openrail++"}


def _fetch_json(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "JSON_CODR/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


class OptimizedModelSearch:
    def __init__(self, fetcher: Callable[[str], list[dict]] | None = None, catalog: OptimizedModelCatalog | None = None):
        self.fetcher = fetcher or _fetch_json
        self.catalog = catalog or OptimizedModelCatalog()
        self.cache: dict[tuple[str, str, int], list[dict]] = {}

    def _pinned(self, provider: str, query: str) -> list[dict]:
        return [{
            "id": model.id, "provider": provider, "repository": model.repository,
            "revision": model.revision, "license": model.license, "format": model.format,
            "device": model.device, "source_url": model.source_url, "source": "pinned",
        } for model in self.catalog.list() if model.provider.value == provider and query.lower() in model.repository.lower()]

    def search(self, provider: str, query: str, limit: int = 10) -> list[dict]:
        if provider not in APPROVED_PROVIDERS:
            raise ValueError("Unsupported optimized-model provider")
        limit = min(max(limit, 1), 20)
        query = query.strip()[:100]
        key = (provider, query.lower(), limit)
        if key in self.cache:
            return self.cache[key]
        format_terms = {"openvino": "openvino", "ryzen_ai": "onnx", "winml": "onnx", "directml": "onnx"}
        url = "https://huggingface.co/api/models?" + urllib.parse.urlencode({"search": f"{query} {format_terms[provider]}", "limit": limit})
        try:
            payload = self.fetcher(url)
            result = []
            for item in payload[:limit]:
                tags = {str(tag).lower() for tag in item.get("tags", [])}
                license_tags = [tag.split(":", 1)[1] for tag in tags if tag.startswith("license:")]
                license_name = license_tags[0] if license_tags else "unknown"
                if format_terms[provider] not in " ".join(tags | {item.get("id", "").lower()}) or license_name not in APPROVED_LICENSES:
                    continue
                repository = item.get("id", "")
                revision = item.get("sha")
                if not repository or not revision:
                    continue
                result.append({
                    "id": f"{provider}/{repository}", "provider": provider, "repository": repository,
                    "revision": revision, "license": license_name,
                    "format": "openvino_ir" if provider == "openvino" else "onnx_genai",
                    "device": "NPU" if provider in {"openvino", "ryzen_ai"} else "AUTO",
                    "source_url": f"https://huggingface.co/{repository}", "source": "remote_unverified",
                })
            self.cache[key] = result or self._pinned(provider, query)
        except (OSError, ValueError, TimeoutError):
            self.cache[key] = self._pinned(provider, query)
        return self.cache[key]
