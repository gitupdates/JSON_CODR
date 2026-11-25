from __future__ import annotations

import asyncio
import base64
import json
import queue
import threading
from contextlib import suppress
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from web_app.models import ChatResult, ReasoningEntry, ReasoningTrace
from web_app.inference.protocol import InferenceEvent, InferenceFinishReason, InferenceRequest
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
        constrained_prompt = (
            f"{prompt}\n\nReturn only one valid JSON object matching this schema exactly. "
            "Do not include markdown or prose.\nJSON SCHEMA:\n"
            + json.dumps(schema, sort_keys=True, separators=(",", ":"))
        )
        request = {
            "model": model,
            "messages": [{"role": "user", "content": constrained_prompt}],
            "stream": True,
            "format": "json",
            "think": False,
            "keep_alive": "5m",
            "options": {"temperature": 0.0, "num_ctx": 2048, "num_predict": 512},
        }
        runner_restart_delays = (0.5, 1.0, 2.0, 4.0)
        for attempt in range(len(runner_restart_delays) + 1):
            content_parts: list[str] = []
            try:
                async for line in self._stream_request("/api/chat", request):
                    chunk = json.loads(line)
                    error_detail = chunk.get("error")
                    if isinstance(error_detail, str) and error_detail.strip():
                        raise OllamaUnavailableError(
                            f"Ollama request failed: {error_detail.strip()}"
                        )
                    message = chunk.get("message")
                    if not isinstance(message, dict):
                        raise ModelOutputError("Ollama returned a malformed JSON chat stream")
                    content_parts.append(str(message.get("content") or ""))
                    if chunk.get("done"):
                        break
            except OllamaUnavailableError as error:
                response = "".join(content_parts).strip()
                if self._is_complete_json_object(response):
                    return response
                transient_runner_restart = self._is_transient_runner_error(error)
                if attempt == len(runner_restart_delays) or not transient_runner_restart:
                    raise
                await asyncio.sleep(runner_restart_delays[attempt])
                continue
            except json.JSONDecodeError as error:
                raise ModelOutputError("Ollama returned malformed JSON chat stream") from error
            response = "".join(content_parts).strip()
            if self._is_complete_json_object(response):
                return response
            raise ModelOutputError("Ollama returned malformed JSON chat output")
        raise OllamaUnavailableError("Ollama request failed")

    @staticmethod
    def _is_complete_json_object(value: str) -> bool:
        try:
            return isinstance(json.loads(value), dict)
        except json.JSONDecodeError:
            return False

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
        request = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": public_reasoning,
            "keep_alive": "5m",
        }
        options: dict[str, int | float] = {
            "num_ctx": 2048,
            "num_predict": 512,
            "temperature": 0.0,
        }
        if model_options:
            options.update(model_options)
        request["options"] = options
        content_parts: list[str] = []
        reasoning_entries: list[ReasoningEntry] = []
        warnings: list[str] = []
        normalizer = ReasoningNormalizer()
        runner_restart_delays = (0.5, 1.0, 2.0, 4.0)
        for attempt in range(len(runner_restart_delays) + 1):
            lines = self._stream_request("/api/chat", request)
            normalizer = ReasoningNormalizer()
            attempt_has_output = False
            attempt_salvaged = False
            retry_delay: float | None = None
            try:
                async for line in lines:
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ModelOutputError("Ollama returned malformed stream JSON") from error
                    error_detail = chunk.get("error")
                    if isinstance(error_detail, str) and error_detail.strip():
                        raise OllamaUnavailableError(
                            f"Ollama request failed: {error_detail.strip()}"
                        )
                    message = chunk.get("message", {})
                    if not isinstance(message, dict):
                        raise ModelOutputError("Ollama returned a malformed stream message")
                    raw_content = str(message.get("content") or "")
                    raw_reasoning = str(message.get("thinking") or "")
                    attempt_has_output = attempt_has_output or bool(raw_content or raw_reasoning)
                    for delta in normalizer.feed({
                        "content": raw_content,
                        "reasoning": raw_reasoning,
                    }):
                        event = self._stream_delta(delta, reasoning_entries, content_parts, warnings)
                        if event:
                            yield event
                    if chunk.get("done"):
                        break
            except OllamaUnavailableError as error:
                transient_restart = self._is_transient_runner_error(error)
                if transient_restart and content_parts:
                    warnings.append(
                        "Ollama runner reset after usable content; preserved the generated answer."
                    )
                    attempt_salvaged = True
                elif (
                    attempt_has_output
                    or attempt == len(runner_restart_delays)
                    or not transient_restart
                ):
                    raise
                else:
                    retry_delay = runner_restart_delays[attempt]
            finally:
                await lines.aclose()
            if attempt_salvaged or retry_delay is None:
                break
            await asyncio.sleep(retry_delay)
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

        connection_restart_delays = (0.25, 0.5, 1.0)
        for attempt in range(len(connection_restart_delays) + 1):
            try:
                return await self._run_request(perform)
            except OllamaUnavailableError as error:
                cause = error.__cause__
                transient_restart = (
                    isinstance(cause, ConnectionResetError)
                    or "forcibly closed" in str(cause)
                )
                if attempt == len(connection_restart_delays) or not transient_restart:
                    raise
                await asyncio.sleep(connection_restart_delays[attempt])
        raise OllamaUnavailableError("Ollama request failed")

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

    async def generate(self, request: InferenceRequest):
        messages = []
        for message in request.messages:
            text = "".join(part.text or "" for part in message.content if part.type.value == "text")
            messages.append({"role": message.role.value, "content": text})
        payload = {
            "model": request.model,
            "messages": messages,
            "stream": True,
            "keep_alive": "5m",
        }
        options = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.top_p is not None:
            options["top_p"] = request.top_p
        if request.max_output_tokens is not None:
            options["num_predict"] = request.max_output_tokens
        if request.stop:
            options["stop"] = list(request.stop)
        if request.seed is not None:
            options["seed"] = request.seed
        if options:
            payload["options"] = options
        cancellation_token = request.cancellation.token if request.cancellation else None
        async for line in self._stream_request("/api/chat", payload):
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as error:
                raise ModelOutputError("Ollama returned malformed stream JSON") from error
            message = chunk.get("message")
            if not isinstance(message, dict):
                raise ModelOutputError("Ollama returned a malformed stream message")
            thinking = str(message.get("thinking") or "")
            if thinking:
                yield InferenceEvent(
                    type="reasoning",
                    text=thinking,
                    requested_model=request.model,
                    effective_model=request.model,
                    route="ollama",
                    cancellation_token=cancellation_token,
                )
            content = str(message.get("content") or "")
            if content:
                yield InferenceEvent(
                    type="content",
                    text=content,
                    requested_model=request.model,
                    effective_model=request.model,
                    route="ollama",
                    cancellation_token=cancellation_token,
                )
            if chunk.get("done"):
                yield InferenceEvent(
                    type="completed",
                    requested_model=request.model,
                    effective_model=request.model,
                    route="ollama",
                    finish_reason=InferenceFinishReason.stop,
                    cancellation_token=cancellation_token,
                )
                break

    async def _stream_request(self, path: str, payload: dict):
        items: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
        stop = threading.Event()
        active_response: dict[str, object] = {}

        def put(kind: str, value: object) -> bool:
            while not stop.is_set():
                try:
                    items.put((kind, value), timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def perform() -> None:
            request = Request(
                f"{self.endpoint}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    active_response["value"] = response
                    for line in response:
                        if stop.is_set():
                            break
                        if line.strip() and not put("line", line):
                            break
            except BaseException as error:
                put("error", error)
            finally:
                active_response.pop("value", None)
                put("done", None)

        worker = asyncio.create_task(asyncio.to_thread(perform))
        try:
            while True:
                kind, value = await asyncio.to_thread(items.get)
                if kind == "line":
                    yield value
                    continue
                if kind == "error":
                    error = value
                    if isinstance(error, TimeoutError):
                        raise ModelTimeoutError("Model request timed out") from error
                    if isinstance(error, HTTPError):
                        detail = ""
                        try:
                            detail = error.read(4096).decode("utf-8", errors="replace").strip()
                        except Exception:
                            pass
                        if detail:
                            raise OllamaUnavailableError(
                                f"Ollama request failed: {detail}"
                            ) from error
                    if isinstance(error, (HTTPError, URLError, OSError)):
                        raise OllamaUnavailableError("Ollama request failed") from error
                    raise error
                break
        finally:
            stop.set()
            response = active_response.get("value")
            close = getattr(response, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
            with suppress(Exception):
                await worker

    async def _run_request(self, operation):
        try:
            return await asyncio.wait_for(asyncio.to_thread(operation), timeout=self.timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError) as error:
            raise ModelTimeoutError("Model request timed out") from error
        except HTTPError as error:
            detail = ""
            try:
                detail = error.read(4096).decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            if detail:
                raise OllamaUnavailableError(f"Ollama request failed: {detail}") from error
            raise OllamaUnavailableError("Ollama request failed") from error
        except (URLError, OSError) as error:
            raise OllamaUnavailableError("Ollama request failed") from error
        except json.JSONDecodeError as error:
            raise ModelOutputError("Ollama returned malformed JSON") from error

    @staticmethod
    def _is_transient_runner_error(error: OllamaUnavailableError) -> bool:
        cause = error.__cause__
        if isinstance(cause, ConnectionResetError) or "forcibly closed" in str(error):
            return True
        return (
            isinstance(cause, HTTPError)
            and cause.code >= 500
            and str(error).strip() == "Ollama request failed"
        )

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
