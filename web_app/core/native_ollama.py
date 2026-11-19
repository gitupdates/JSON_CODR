from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from web_app.models import ChatResult, ReasoningEntry, ReasoningTrace
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaUnavailableError
from web_app.reasoning import ReasoningNormalizer


class NativeOllamaTransport:
    supports_model_options = True

    def __init__(self, endpoint: str, timeout_seconds: int = 180) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("native Ollama endpoint must use HTTP on loopback")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("native Ollama endpoint must be a plain loopback origin")
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def health(self) -> dict[str, bool]:
        try:
            await self._json_request("/api/tags")
            return {"ollama": True}
        except OllamaUnavailableError:
            return {"ollama": False}

    async def list_models(self) -> list[dict]:
        payload = await self._json_request("/api/tags")
        models = payload.get("models", [])
        if not isinstance(models, list):
            raise ModelOutputError("Ollama returned a malformed model list")
        return [item for item in models if isinstance(item, dict)]

    async def json_chat(self, model: str, prompt: str, schema: dict) -> str:
        payload = await self._post_json("/api/chat", {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.0},
        })
        message = payload.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelOutputError("Ollama returned malformed JSON chat output")
        return message["content"]

    async def stream_chat(
        self,
        model: str,
        prompt: str,
        images: list[Path] | tuple[Path, ...] = (),
        public_reasoning: bool = False,
        model_options: dict[str, int | float] | None = None,
    ):
        messages = []
        if public_reasoning:
            messages.append({
                "role": "system",
                "content": (
                    "Provide a concise public rationale through the provider reasoning channel, then a clean answer. "
                    "State evidence and uncertainty; do not claim unavailable tools were used."
                ),
            })
        encoded_images = [base64.b64encode(Path(image).read_bytes()).decode("ascii") for image in images]
        user_message = {"role": "user", "content": prompt}
        if encoded_images:
            user_message["images"] = encoded_images
        messages.append(user_message)
        request = {"model": model, "messages": messages, "stream": True}
        if public_reasoning:
            request["think"] = True
        if model_options:
            request["options"] = model_options
        lines = await self._stream_request("/api/chat", request)
        normalizer = ReasoningNormalizer()
        content_parts: list[str] = []
        reasoning_entries: list[ReasoningEntry] = []
        warnings: list[str] = []
        for line in lines:
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as error:
                raise ModelOutputError("Ollama returned malformed stream JSON") from error
            message = chunk.get("message", {})
            if not isinstance(message, dict):
                raise ModelOutputError("Ollama returned a malformed stream message")
            for delta in normalizer.feed({
                "content": str(message.get("content") or ""),
                "reasoning": str(message.get("thinking") or ""),
            }):
                event = self._stream_delta(delta, reasoning_entries, content_parts, warnings)
                if event:
                    yield event
        for delta in normalizer.finish():
            event = self._stream_delta(delta, reasoning_entries, content_parts, warnings)
            if event:
                yield event
        content = "".join(content_parts).strip()
        if not content:
            raise ModelOutputError("Model returned no answer content")
        summary = next((line.strip() for line in content.splitlines() if line.strip()), "Model response")[:240]
        reasoning = ReasoningTrace(entries=reasoning_entries, warnings=warnings) if reasoning_entries or warnings else None
        yield {
            "type": "completed",
            "result": ChatResult(model=model, status="success", summary=summary, content=content, reasoning=reasoning),
        }

    async def _json_request(self, path: str) -> dict:
        def perform() -> dict:
            request = Request(f"{self.endpoint}{path}", method="GET")
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, dict):
                raise ModelOutputError("Ollama returned malformed JSON")
            return payload

        return await self._run_request(perform)

    async def _post_json(self, path: str, payload: dict) -> dict:
        def perform() -> dict:
            request = Request(
                f"{self.endpoint}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read())
            if not isinstance(result, dict):
                raise ModelOutputError("Ollama returned malformed JSON")
            return result

        return await self._run_request(perform)

    async def _stream_request(self, path: str, payload: dict) -> list[bytes]:
        def perform() -> list[bytes]:
            request = Request(
                f"{self.endpoint}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return [line for line in response if line.strip()]

        return await self._run_request(perform)

    async def _run_request(self, operation):
        try:
            return await asyncio.wait_for(asyncio.to_thread(operation), timeout=self.timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError) as error:
            raise ModelTimeoutError("Model request timed out") from error
        except (HTTPError, URLError, OSError) as error:
            raise OllamaUnavailableError("Ollama request failed") from error
        except json.JSONDecodeError as error:
            raise ModelOutputError("Ollama returned malformed JSON") from error

    @staticmethod
    def _stream_delta(delta, reasoning_entries, content_parts, warnings):
        if delta.channel == "content":
            content_parts.append(delta.text)
            return {"type": "content", "text": delta.text}
        if delta.channel == "reasoning":
            reasoning_entries.append(ReasoningEntry(
                sequence=len(reasoning_entries),
                kind="analysis",
                text=delta.text,
                provenance=delta.provenance,
            ))
            return {"type": "reasoning", "text": delta.text, "provenance": delta.provenance}
        warnings.append(delta.text)
        return {"type": "warning", "text": delta.text}
