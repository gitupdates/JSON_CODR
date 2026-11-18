import asyncio
from typing import Any, Callable, Dict, List, Optional

import ollama
from pydantic import ValidationError

from cli import StructuredCLIResponse, load_config, parse_response_content
from web_app.models import ChatResult, ConversionBundle, GpuProfileSettings, ReasoningEntry, ReasoningTrace
from web_app.reasoning import ReasoningNormalizer


class OllamaUnavailableError(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    def __init__(self, message: str, *, provider_events: Optional[List[dict[str, object]]] = None) -> None:
        super().__init__(message)
        self.provider_events = list(provider_events or [])


class ModelTimeoutError(RuntimeError):
    pass


class OllamaService:
    def __init__(
        self,
        client: Optional[Any] = None,
        timeout_seconds: int = 180,
        optimization_provider: Optional[Callable[[str], GpuProfileSettings]] = None,
    ) -> None:
        self.config = load_config()
        self.client = client or ollama.AsyncClient(host=self.config["host"])
        self.timeout_seconds = timeout_seconds
        self.optimization_provider = optimization_provider or (lambda model: GpuProfileSettings())

    def set_optimization_provider(self, provider: Callable[[str], GpuProfileSettings]) -> None:
        self.optimization_provider = provider

    async def _chat_with_optimization(self, model: str, request: dict):
        options = self.optimization_provider(model).ollama_options()
        if options:
            request["options"] = options
        try:
            return await asyncio.wait_for(self.client.chat(**request), timeout=self.timeout_seconds)
        except Exception as initial_error:
            if options:
                request.pop("options", None)
                try:
                    return await asyncio.wait_for(self.client.chat(**request), timeout=self.timeout_seconds)
                except Exception:
                    pass
            if request.get("think") is True:
                request.pop("think", None)
                return await asyncio.wait_for(self.client.chat(**request), timeout=self.timeout_seconds)
            raise initial_error

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

    async def running_models(self) -> List[dict]:
        try:
            response = await asyncio.wait_for(self.client.ps(), timeout=5)
        except Exception:
            return []
        payload = response.model_dump() if hasattr(response, "model_dump") else response
        result = []
        for item in payload.get("models", []):
            size = int(item.get("size") or 0)
            size_vram = int(item.get("size_vram") or 0)
            gpu_percent = round(size_vram * 100 / size) if size else 0
            result.append({
                "name": item.get("model") or item.get("name"),
                "size": size,
                "size_vram": size_vram,
                "processor": f"{gpu_percent}% GPU" if gpu_percent else "100% CPU",
            })
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

    async def supports_tools(self, model: str) -> bool:
        resolved = self._resolve(model)
        verified = self.config.get("verified_tool_models")
        if isinstance(verified, list):
            return resolved in verified
        try:
            response = await asyncio.wait_for(self.client.show(resolved), timeout=5)
        except Exception:
            return False
        payload = response.model_dump() if hasattr(response, "model_dump") else response
        return "tools" in payload.get("capabilities", [])

    async def tool_compatibility(self, model: str) -> dict:
        resolved = self._resolve(model)
        try:
            response = await asyncio.wait_for(self.client.show(resolved), timeout=5)
            payload = response.model_dump() if hasattr(response, "model_dump") else response
            advertised = "tools" in payload.get("capabilities", [])
        except Exception:
            advertised = False

        verified = self.config.get("verified_tool_models")
        verified_models = verified if isinstance(verified, list) else []
        if resolved in verified_models:
            route = "native_verified"
            effective_model = resolved
        else:
            fallback = str(self.config.get("tool_fallback_model", "")).strip()
            effective_model = fallback if fallback in verified_models else None
            route = "delegated_verified" if effective_model else "unavailable"
        return {
            "requested_model": resolved,
            "advertised_tools": advertised,
            "native_tools_verified": resolved in verified_models,
            "route": route,
            "effective_tool_model": effective_model,
            "available": effective_model is not None,
        }

    async def generate_deterministic(
        self, model: str, messages: List[dict], temperature: float = 0.0
    ) -> str:
        resolved = self._resolve(model)
        live = await self._live_models()
        if resolved not in live:
            raise OllamaUnavailableError("Model is not installed")
        try:
            response = await asyncio.wait_for(
                self.client.chat(
                    model=resolved,
                    messages=messages,
                    options={"temperature": temperature, "num_predict": 512},
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise ModelTimeoutError("Model request timed out") from error
        except Exception as error:
            raise OllamaUnavailableError("Ollama request failed") from error
        return str(response.message.content if hasattr(response, "message") else response["message"]["content"])

    def _resolve(self, requested: str) -> str:
        configured = self.config["jury_models"]
        if requested in configured:
            return requested
        matches = [name for name in configured if requested.lower() in name.lower()]
        if len(matches) != 1:
            raise ValueError("Unknown or ambiguous model")
        return matches[0]

    async def chat(
        self,
        model: str,
        prompt: str,
        images: Optional[List[Any]] = None,
        allow_repair: bool = True,
    ) -> ChatResult:
        resolved = self._resolve(model)
        live = await self._live_models()
        if resolved not in live:
            raise OllamaUnavailableError("Model is not installed")
        request = {
            "model": resolved,
            "messages": [{"role": "user", "content": prompt, "images": images or None}],
            "format": StructuredCLIResponse.model_json_schema(),
        }
        try:
            response = await self._chat_with_optimization(resolved, request)
        except asyncio.TimeoutError as error:
            raise ModelTimeoutError("Model request timed out") from error
        except Exception as error:
            raise OllamaUnavailableError("Ollama request failed") from error
        try:
            raw = response.message.content if hasattr(response, "message") else response["message"]["content"]
            parsed = parse_response_content(raw)
            if not parsed.content.strip():
                raise ValueError("Structured response content is empty")
        except (ValidationError, KeyError, TypeError, AttributeError, ValueError) as error:
            initial_raw = str(raw) if "raw" in locals() else ""
            plain = initial_raw.strip()
            if not allow_repair:
                summary = next((line.strip() for line in plain.splitlines() if line.strip()), plain)[:240]
                return ChatResult(
                    model=resolved,
                    status="success",
                    summary=summary,
                    content=plain,
                    error="structured_output_fallback",
                    provider_events=[{
                        "type": "structured_output_fallback",
                        "initial_raw": initial_raw,
                    }],
                )
            repair_event: dict[str, object] = {
                "type": "schema_repair",
                "initial_raw": initial_raw,
                "repaired_raw": None,
            }
            repair_request = {
                "model": resolved,
                "messages": [
                    *request["messages"],
                    {"role": "assistant", "content": plain},
                    {
                        "role": "user",
                        "content": (
                            "Reformat your previous answer into the required JSON response schema. "
                            "Preserve its meaning, add no new claims, and return JSON only."
                        ),
                    },
                ],
                "format": StructuredCLIResponse.model_json_schema(),
            }
            try:
                repaired_response = await self._chat_with_optimization(resolved, repair_request)
                repaired_raw = (
                    repaired_response.message.content
                    if hasattr(repaired_response, "message")
                    else repaired_response["message"]["content"]
                )
                repaired = parse_response_content(repaired_raw)
                if not repaired.content.strip():
                    raise ValueError("Repaired structured response content is empty")
                repair_event["repaired_raw"] = str(repaired_raw)
                return ChatResult(
                    model=resolved,
                    **repaired.model_dump(),
                    provider_events=[repair_event],
                )
            except Exception as repair_error:
                if "repaired_raw" in locals():
                    repair_event["repaired_raw"] = str(repaired_raw)
                repair_event["error"] = f"{type(repair_error).__name__}: {repair_error}"
                if not plain:
                    raise ModelOutputError(
                        "Malformed structured output",
                        provider_events=[repair_event],
                    ) from repair_error
            summary = next((line.strip() for line in plain.splitlines() if line.strip()), plain)[:240]
            return ChatResult(
                model=resolved,
                status="success",
                summary=summary,
                content=plain,
                error="structured_output_fallback",
                provider_events=[repair_event],
            )
        return ChatResult(
            model=resolved,
            **parsed.model_dump(),
            provider_events=[{"type": "structured_response", "raw": str(raw)}],
        )

    async def stream_chat(
        self,
        model: str,
        prompt: str,
        images: Optional[List[Any]] = None,
        public_reasoning: bool = False,
    ):
        resolved = self._resolve(model)
        live = await self._live_models()
        if resolved not in live:
            raise OllamaUnavailableError("Model is not installed")
        messages = []
        if public_reasoning:
            messages.append({
                "role": "system",
                "content": (
                    "Use the runtime's separate reasoning channel for a concise, auditable public rationale, "
                    "then provide a clean final answer. State assumptions, evidence, uncertainty, and verification. "
                    "Do not claim tools or files were used unless they were supplied."
                ),
            })
        messages.append({"role": "user", "content": prompt, "images": images or None})
        request = {"model": resolved, "messages": messages, "stream": True}
        if public_reasoning:
            request["think"] = True
        normalizer = ReasoningNormalizer()
        content_parts: list[str] = []
        reasoning_entries: list[ReasoningEntry] = []
        warnings: list[str] = []
        try:
            attempts = [request]
            if request.get("think") is True:
                attempts.append({key: value for key, value in request.items() if key != "think"})
            for attempt in attempts:
                received_chunk = False
                try:
                    stream = await self._chat_with_optimization(resolved, attempt)
                    async with asyncio.timeout(self.timeout_seconds):
                        async for chunk in stream:
                            received_chunk = True
                            message = chunk.message if hasattr(chunk, "message") else chunk.get("message", {})
                            content = getattr(message, "content", None) if not isinstance(message, dict) else message.get("content")
                            reasoning = getattr(message, "thinking", None) if not isinstance(message, dict) else message.get("thinking")
                            for delta in normalizer.feed({"content": content or "", "reasoning": reasoning or ""}):
                                event = self._stream_delta(delta, reasoning_entries, content_parts, warnings)
                                if event:
                                    yield event
                    break
                except ollama.ResponseError as error:
                    unsupported_thinking = (
                        attempt.get("think") is True
                        and not received_chunk
                        and "does not support thinking" in str(error).casefold()
                    )
                    if unsupported_thinking:
                        continue
                    raise
            for delta in normalizer.finish():
                event = self._stream_delta(delta, reasoning_entries, content_parts, warnings)
                if event:
                    yield event
        except TimeoutError as error:
            raise ModelTimeoutError("Model request timed out") from error
        except (ModelTimeoutError, ModelOutputError, OllamaUnavailableError, ValueError):
            raise
        except Exception as error:
            raise OllamaUnavailableError("Ollama request failed") from error
        content = "".join(content_parts).strip()
        if not content:
            raise ModelOutputError("Model returned no answer content")
        summary = next((line.strip() for line in content.splitlines() if line.strip()), "Model response")[:240]
        trace = ReasoningTrace(entries=reasoning_entries, warnings=warnings) if reasoning_entries or warnings else None
        yield {
            "type": "completed",
            "result": ChatResult(model=resolved, status="success", summary=summary, content=content, reasoning=trace),
        }

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

    async def convert_archive(self, model: str, prompt: str) -> ConversionBundle:
        resolved = self._resolve(model)
        live = await self._live_models()
        if resolved not in live:
            raise OllamaUnavailableError("Model is not installed")
        conversion_prompt = (
            prompt
            + "\n\nCONVERSION OUTPUT REQUIREMENTS:\n"
            "Create new, self-contained files adapted for a generic local LLM system without Claude-specific "
            "runtime assumptions. Include README-CONVERTED.md with detailed usage, syntax, compatibility notes, "
            "and limitations. Include each converted skill as a separate relative file. Do not claim files were "
            "installed or executed. Return only the requested structured conversion bundle."
        )
        try:
            response = await self._chat_with_optimization(resolved, {
                "model": resolved,
                "messages": [{"role": "user", "content": conversion_prompt}],
                "format": ConversionBundle.model_json_schema(),
            })
        except asyncio.TimeoutError as error:
            raise ModelTimeoutError("Model conversion timed out") from error
        except Exception as error:
            raise OllamaUnavailableError("Ollama conversion failed") from error
        try:
            raw = response.message.content if hasattr(response, "message") else response["message"]["content"]
            bundle = ConversionBundle.model_validate_json(raw)
        except (ValidationError, KeyError, TypeError, AttributeError) as error:
            raise ModelOutputError("Malformed conversion output") from error
        if not bundle.files:
            raise ModelOutputError("Conversion produced no files")
        return bundle
