from __future__ import annotations

import json

from web_app.models import BrokerActionRequest


class GitActionAdapter:
    def __init__(self, max_response_bytes: int = 250_000, verification_checks: dict[str, list[str]] | None = None) -> None:
        self.max_response_bytes = max_response_bytes
        self.verification_checks = verification_checks or {}

    def prompt_contract(self, project_root: str, baseline_fingerprint: str) -> str:
        return (
            "Return exactly one JSON object and no prose or Markdown. "
            "Use schema_version 1 with project_root, baseline_fingerprint, and actions. "
            "Allowed actions are status, read, apply_patch, verify, commit, sync, and push. "
            "Patches must be unified diffs; shell commands and environment variables are forbidden. "
            f"Allowed verification checks are {sorted(self.verification_checks)}. "
            f"project_root={project_root!r}; baseline_fingerprint={baseline_fingerprint!r}."
        )

    def parse(self, response: str) -> BrokerActionRequest:
        if len(response.encode("utf-8")) > self.max_response_bytes:
            raise ValueError("Broker response is too large")
        if response != response.strip() or not response.startswith("{") or not response.endswith("}"):
            raise ValueError("Broker response must be exactly one JSON object")
        try:
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"Broker response contains duplicate key: {key}")
                    result[key] = value
                return result

            payload = json.loads(response, object_pairs_hook=unique_object)
        except json.JSONDecodeError as error:
            raise ValueError("Broker response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Broker response must be a JSON object")
        return BrokerActionRequest.model_validate(payload)


def classify_tool_support_error(message: str) -> dict[str, str]:
    normalized = message.casefold()
    if "does not support tools" in normalized or "tool support" in normalized and "not" in normalized:
        return {
            "mode": "broker_adapter",
            "message": "This model uses the JSON_CODR broker adapter for project tools.",
        }
    return {"mode": "unknown", "message": "Tool compatibility has not been verified."}
