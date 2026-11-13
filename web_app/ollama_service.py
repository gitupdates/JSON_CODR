import asyncio
from typing import Any, Dict, List, Optional

import ollama
from pydantic import ValidationError

from cli import StructuredCLIResponse, load_config, parse_response_content
from web_app.models import ChatResult


class OllamaUnavailableError(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    pass


class ModelTimeoutError(RuntimeError):
    pass


class OllamaService:
    def __init__(self, client: Optional[Any] = None, timeout_seconds: int = 180) -> None:
        self.config = load_config()
        self.client = client or ollama.AsyncClient(host=self.config["host"])
        self.timeout_seconds = timeout_seconds

    async def health(self) -> Dict[str, bool]:
        try:
            await asyncio.wait_for(self.client.list(), timeout=2)
            return {"ollama": True}
        except Exception:
            return {"ollama": False}

    async def _live_models(self) -> Dict[str, dict]:
        try:
            response = await asyncio.wait_for(self.client.list(), timeout=5)
        except Exception as error:
            raise OllamaUnavailableError("Ollama is unavailable") from error
        payload = response.model_dump() if hasattr(response, "model_dump") else response
        return {item.get("model") or item.get("name"): item for item in payload.get("models", [])}

    async def list_models(self) -> List[dict]:
        live = await self._live_models()
        result = []
        for name in self.config["jury_models"]:
            item = live.get(name)
            details = (item or {}).get("details", {})
            result.append(
                {
                    "name": name,
                    "installed": item is not None,
                    "size": (item or {}).get("size"),
                    "quantization": details.get("quantization_level"),
                    "context_length": details.get("context_length"),
                    "capabilities": (item or {}).get("capabilities", []),
                }
            )
        return result

    async def supports_vision(self, model: str) -> bool:
        resolved = self._resolve(model)
        try:
            response = await asyncio.wait_for(self.client.show(resolved), timeout=5)
        except Exception:
            return False
        payload = response.model_dump() if hasattr(response, "model_dump") else response
        capabilities = payload.get("capabilities", [])
        return "vision" in capabilities

    def _resolve(self, requested: str) -> str:
        configured = self.config["jury_models"]
        if requested in configured:
            return requested
        matches = [name for name in configured if requested.lower() in name.lower()]
        if len(matches) != 1:
            raise ValueError("Unknown or ambiguous model")
        return matches[0]

    async def chat(self, model: str, prompt: str, images: Optional[List[Any]] = None) -> ChatResult:
        resolved = self._resolve(model)
        live = await self._live_models()
        if resolved not in live:
            raise OllamaUnavailableError("Model is not installed")
        try:
            response = await asyncio.wait_for(
                self.client.chat(
                    model=resolved,
                    messages=[{"role": "user", "content": prompt, "images": images or None}],
                    format=StructuredCLIResponse.model_json_schema(),
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise ModelTimeoutError("Model request timed out") from error
        except Exception as error:
            raise OllamaUnavailableError("Ollama request failed") from error
        try:
            raw = response.message.content if hasattr(response, "message") else response["message"]["content"]
            parsed = parse_response_content(raw)
        except (ValidationError, KeyError, TypeError, AttributeError) as error:
            raise ModelOutputError("Malformed structured output") from error
        return ChatResult(model=resolved, **parsed.model_dump())
