from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ContentPartType(str, Enum):
    text = "text"
    image = "image"
    tool_call = "tool_call"
    tool_result = "tool_result"


class ContentPart(_Contract):
    type: ContentPartType
    text: str | None = None
    image_url: str | None = None
    mime_type: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, JsonValue] | None = None
    result: JsonValue | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        required = {
            ContentPartType.text: self.text,
            ContentPartType.image: self.image_url,
            ContentPartType.tool_call: self.tool_name,
            ContentPartType.tool_result: self.tool_call_id,
        }
        if required[self.type] is None:
            raise ValueError(f"{self.type.value} content is missing its required payload")
        if self.type == ContentPartType.tool_call and self.tool_call_id is None:
            raise ValueError("tool_call content requires tool_call_id")
        return self


class InferenceRole(str, Enum):
    system = "system"
    developer = "developer"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class InferenceMessage(_Contract):
    role: InferenceRole
    content: tuple[ContentPart, ...] = Field(min_length=1)
    name: str | None = None


class ToolDefinition(_Contract):
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class ToolChoiceFunction(_Contract):
    name: str = Field(min_length=1)


ToolChoice = Literal["auto", "none", "required"] | ToolChoiceFunction


class ResponseFormat(_Contract):
    type: Literal["text", "json_object", "json_schema"] = "text"
    json_schema: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_schema(self):
        if self.type == "json_schema" and self.json_schema is None:
            raise ValueError("json_schema response format requires a schema")
        return self


class CancellationMetadata(_Contract):
    token: str = Field(min_length=1)
    disconnect_cancels: bool = False


class InferenceRequest(_Contract):
    request_id: str | None = None
    model: str = Field(min_length=1)
    messages: tuple[InferenceMessage, ...] = Field(min_length=1)
    tools: tuple[ToolDefinition, ...] = ()
    tool_choice: ToolChoice = "auto"
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_output_tokens: int | None = Field(default=None, gt=0)
    stop: tuple[str, ...] = ()
    seed: int | None = None
    response_format: ResponseFormat = Field(default_factory=ResponseFormat)
    public_reasoning: bool = False
    cancellation: CancellationMetadata | None = None


class InferenceUsage(_Contract):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class InferenceFinishReason(str, Enum):
    stop = "stop"
    length = "length"
    tool_calls = "tool_calls"
    cancelled = "cancelled"
    error = "error"


class InferenceEventType(str, Enum):
    content = "content"
    reasoning = "reasoning"
    tool_call = "tool_call"
    warning = "warning"
    usage = "usage"
    completed = "completed"
    error = "error"


class InferenceEvent(_Contract):
    type: InferenceEventType
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    warning: str | None = None
    requested_model: str
    effective_model: str
    route: str
    usage: InferenceUsage | None = None
    finish_reason: InferenceFinishReason | None = None
    cancellation_token: str | None = None
