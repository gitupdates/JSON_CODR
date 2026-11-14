import json
import os
import re
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from web_app.models import ActionSuggestion


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "jury_config.json")


class StructuredCLIResponse(BaseModel):
    status: str = Field(description="Execution status of the CLI prompt response")
    summary: str = Field(description="Brief summary of the generated response")
    content: str = Field(description="Detailed response content")
    actions: list[ActionSuggestion] = Field(default_factory=list, max_length=5)

    @field_validator("actions", mode="before")
    @classmethod
    def drop_invalid_actions(cls, value):
        if not isinstance(value, list):
            return []
        valid = []
        for item in value[:5]:
            try:
                valid.append(ActionSuggestion.model_validate(item))
            except (ValidationError, TypeError, ValueError):
                continue
        return valid


def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def resolve_model_name(requested: Optional[str], config: dict) -> str:
    installed = config.get("jury_models", [])
    if not requested:
        return config["model"]
    if requested in installed:
        return requested
    matches = [model for model in installed if requested.lower() in model.lower()]
    if len(matches) == 1:
        return matches[0]
    return requested


def parse_response_content(raw_content: str) -> StructuredCLIResponse:
    try:
        return StructuredCLIResponse.model_validate_json(raw_content)
    except Exception:
        pass
    cleaned = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1)
    else:
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        cleaned = match.group(1) if match else cleaned
    return StructuredCLIResponse.model_validate_json(cleaned)
