from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field


class NormalizedDelta(BaseModel):
    channel: Literal["reasoning", "content", "warning"]
    text: str = Field(min_length=1)
    provenance: Literal["native_provider", "provider_tag", "public_rationale"] | None = None


class ReasoningNormalizer:
    OPEN_TAG = "<think>"
    CLOSE_TAG = "</think>"

    def __init__(self, *, max_characters: int = 1_000_000) -> None:
        self._buffer = ""
        self._inside_tag = False
        self._characters = 0
        self._max_characters = max_characters

    def feed(self, delta: Mapping[str, object] | str) -> list[NormalizedDelta]:
        payload = {"content": delta} if isinstance(delta, str) else delta
        output: list[NormalizedDelta] = []
        reasoning = payload.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            self._consume(reasoning)
            output.append(NormalizedDelta(channel="reasoning", text=reasoning, provenance="native_provider"))
        rationale = payload.get("rationale")
        if isinstance(rationale, str) and rationale:
            self._consume(rationale)
            output.append(NormalizedDelta(channel="reasoning", text=rationale, provenance="public_rationale"))
        content = payload.get("content")
        if isinstance(content, str) and content:
            self._consume(content)
            self._buffer += content
            output.extend(self._drain(final=False))
        return output

    def finish(self) -> list[NormalizedDelta]:
        output = self._drain(final=True)
        if self._inside_tag:
            output.append(NormalizedDelta(channel="warning", text="Provider reasoning tag was not closed"))
        self._inside_tag = False
        self._buffer = ""
        return output

    def _consume(self, text: str) -> None:
        self._characters += len(text)
        if self._characters > self._max_characters:
            raise ValueError("Reasoning stream exceeds configured character limit")

    def _drain(self, *, final: bool) -> list[NormalizedDelta]:
        output: list[NormalizedDelta] = []
        while self._buffer:
            marker = self.CLOSE_TAG if self._inside_tag else self.OPEN_TAG
            index = self._buffer.find(marker)
            if index >= 0:
                text = self._buffer[:index]
                if text:
                    output.append(self._text_delta(text))
                self._buffer = self._buffer[index + len(marker):]
                self._inside_tag = not self._inside_tag
                continue
            if final:
                output.append(self._text_delta(self._buffer))
                self._buffer = ""
                break
            keep = min(len(marker) - 1, len(self._buffer))
            emit = self._buffer[:-keep] if keep else self._buffer
            if emit:
                output.append(self._text_delta(emit))
                self._buffer = self._buffer[-keep:] if keep else ""
            break
        return output

    def _text_delta(self, text: str) -> NormalizedDelta:
        if self._inside_tag:
            return NormalizedDelta(channel="reasoning", text=text, provenance="provider_tag")
        return NormalizedDelta(channel="content", text=text)
