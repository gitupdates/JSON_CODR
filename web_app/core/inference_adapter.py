from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from web_app.core.adapters import AdapterEvent, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaUnavailableError


class InferenceAdapter:
    def __init__(
        self,
        backend,
        *,
        prepare_prompt: Callable[[CapabilityCall, str], tuple[str, Mapping[str, Any]]] | None = None,
    ) -> None:
        self._backend = backend
        self._prepare_prompt = prepare_prompt

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        model = call.arguments.get("model")
        prompt = call.arguments.get("prompt")
        images = call.arguments.get("images", ())
        if not isinstance(model, str) or not isinstance(prompt, str):
            raise ValueError("inference generation requires model and prompt")
        metadata: Mapping[str, Any] = {}
        if self._prepare_prompt is not None:
            prompt, metadata = self._prepare_prompt(call, prompt)
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
        yield AdapterEvent(
            event_type="inference.completed",
            payload={
                "requested_model_id": model,
                "effective_model_id": result.model,
                "fallback_used": result.model != model,
                "result": result.model_dump(mode="json"),
            },
        )
