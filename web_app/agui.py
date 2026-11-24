from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from ag_ui.core import (
    PROTOCOL_VERSION,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder

from web_app.ollama_service import ModelOutputError, ModelTimeoutError, OllamaUnavailableError


_MAX_MESSAGES = 50
_MAX_MESSAGE_CHARS = 16_000
_MAX_PROMPT_CHARS = 64_000


def build_prompt(run_input: RunAgentInput) -> str:
    if not run_input.messages:
        raise ValueError("AG-UI run requires at least one message")
    if len(run_input.messages) > _MAX_MESSAGES:
        raise ValueError(f"AG-UI run exceeds the {_MAX_MESSAGES}-message limit")

    messages = []
    total = 0
    for message in run_input.messages:
        role = str(message.role).upper()
        content = message.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for part in content:
                if getattr(part, "type", None) != "text":
                    raise ValueError("This AG-UI endpoint accepts text messages only")
                parts.append(str(part.text))
            text = "".join(parts)
        else:
            raise ValueError("AG-UI message content must be text")
        if len(text) > _MAX_MESSAGE_CHARS:
            raise ValueError("AG-UI message exceeds the 16000-character limit")
        if text.strip():
            messages.append(f"{role}:\n{text}")
            total += len(text)
    if not messages:
        raise ValueError("AG-UI run requires non-empty text")
    if total > _MAX_PROMPT_CHARS:
        raise ValueError("AG-UI conversation exceeds the 64000-character limit")
    return "\n\n".join(messages)


async def stream_events(
    run_input: RunAgentInput,
    *,
    model: str,
    prompt: str,
    backend,
    encoder: EventEncoder,
) -> AsyncIterator[str | bytes]:
    yield encoder.encode(RunStartedEvent(
        thread_id=run_input.thread_id,
        run_id=run_input.run_id,
        protocol_version=PROTOCOL_VERSION,
        parent_run_id=run_input.parent_run_id,
    ))
    message_id = str(uuid4())
    yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
    received_content = False

    try:
        async for event in backend.stream_chat(model, prompt):
            if event.get("type") == "content":
                text = event.get("text")
                if isinstance(text, str) and text:
                    received_content = True
                    yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=text))
            elif event.get("type") == "completed" and not received_content:
                result = event.get("result")
                text = result.get("content") if isinstance(result, dict) else getattr(result, "content", None)
                if isinstance(text, str) and text:
                    received_content = True
                    yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=text))
        if not received_content:
            raise ModelOutputError("Model returned no answer content")
    except (ModelOutputError, ModelTimeoutError, OllamaUnavailableError, ValueError) as error:
        yield encoder.encode(TextMessageEndEvent(message_id=message_id))
        yield encoder.encode(RunErrorEvent(message=str(error), code=_error_code(error)))
        return

    yield encoder.encode(TextMessageEndEvent(message_id=message_id))
    yield encoder.encode(RunFinishedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id))


def _error_code(error: Exception) -> str:
    if isinstance(error, ModelTimeoutError):
        return "model_timeout"
    if isinstance(error, ModelOutputError):
        return "model_output"
    if isinstance(error, OllamaUnavailableError):
        return "model_unavailable"
    return "invalid_request"
