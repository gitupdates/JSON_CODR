from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from web_app.core.adapters import AdapterEvent, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.model_tags import ModelTagRegistry
from web_app.model_compatibility import is_model_runnable
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaUnavailableError


class InferenceAdapter:
    def __init__(
        self,
        backend,
        *,
        prepare_prompt: Callable[[CapabilityCall, str], tuple[str, Mapping[str, Any]]] | None = None,
        model_registry: ModelTagRegistry | None = None,
    ) -> None:
        self._backend = backend
        self._prepare_prompt = prepare_prompt
        self._model_registry = model_registry

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        requested_model = call.arguments.get("model")
        prompt = call.arguments.get("prompt")
        images = call.arguments.get("images", ())
        if not isinstance(requested_model, str) or not isinstance(prompt, str):
            raise ValueError("inference generation requires model and prompt")
        model, model_options = await self._resolve_model(requested_model)
        metadata: Mapping[str, Any] = {}
        if self._prepare_prompt is not None:
            prompt, metadata = self._prepare_prompt(call, prompt)
        stream_chat = getattr(self._backend, "stream_chat", None)
        if callable(stream_chat):
            try:
                stream_arguments = {
                    "images": [Path(image) for image in images],
                    "public_reasoning": bool(call.arguments.get("public_reasoning", False)),
                }
                if getattr(self._backend, "supports_model_options", False) and model_options:
                    stream_arguments["model_options"] = dict(model_options)
                async for delta in stream_chat(model, prompt, **stream_arguments):
                    event_type = str(delta.get("type", ""))
                    if event_type == "completed":
                        result = delta.get("result")
                        if not hasattr(result, "model_dump"):
                            raise ModelOutputError("Malformed streamed completion")
                        if metadata:
                            result = type(result).model_validate({**result.model_dump(mode="json"), **metadata})
                        yield self._completed(requested_model, result)
                    elif event_type == "reasoning":
                        yield AdapterEvent(
                            event_type="inference.reasoning.delta",
                            payload={"text": str(delta.get("text", "")), "provenance": str(delta.get("provenance", "native_provider"))},
                        )
                    elif event_type == "content":
                        yield AdapterEvent(event_type="inference.content.delta", payload={"text": str(delta.get("text", ""))})
                    elif event_type == "reference":
                        yield AdapterEvent(event_type="inference.reference", payload=dict(delta.get("reference", {})))
                    elif event_type == "warning":
                        yield AdapterEvent(event_type="inference.warning", payload={"message": str(delta.get("text", ""))})
                return
            except ModelTimeoutError as error:
                raise CapabilityExecutionError("model_timeout", str(error)) from error
            except ModelOutputError as error:
                raise CapabilityExecutionError("model_output", str(error)) from error
            except OllamaUnavailableError as error:
                raise CapabilityExecutionError("model_unavailable", str(error)) from error
            except ValueError as error:
                raise CapabilityExecutionError("invalid_request", str(error)) from error
        try:
            result = await self._backend.chat(model, prompt, images=[Path(image) for image in images])
        except ModelTimeoutError as error:
            raise CapabilityExecutionError("model_timeout", str(error)) from error
        except ModelOutputError as error:
            raise CapabilityExecutionError("model_output", str(error)) from error
        except OllamaUnavailableError as error:
            raise CapabilityExecutionError("model_unavailable", str(error)) from error
        except ValueError as error:
            raise CapabilityExecutionError("invalid_request", str(error)) from error
        if metadata:
            result = type(result).model_validate({**result.model_dump(mode="json"), **metadata})
        yield self._completed(requested_model, result)

    async def _resolve_model(self, requested_model: str) -> tuple[str, Mapping[str, int | float]]:
        if self._model_registry is None:
            return requested_model, {}
        models = await self._backend.list_models()
        installed = {
            str(item.get("name") or item.get("model"))
            for item in models
            if (
                isinstance(item, Mapping)
                and (item.get("name") or item.get("model"))
                and is_model_runnable(item)
            )
        }
        route = self._model_registry.resolve(requested_model, installed)
        return route.effective_model, route.options

    @staticmethod
    def _completed(model: str, result) -> AdapterEvent:
        return AdapterEvent(
            event_type="inference.completed",
            payload={
                "requested_model_id": model,
                "effective_model_id": result.model,
                "fallback_used": result.model != model,
                "result": result.model_dump(mode="json"),
            },
        )
