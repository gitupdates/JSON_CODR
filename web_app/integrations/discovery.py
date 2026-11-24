from __future__ import annotations

from urllib.parse import urlsplit

from web_app.version import APP_VERSION


def _http_origin(value: str) -> str:
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("discovery URLs must use http or https")
    return f"{parsed.scheme}://{parsed.netloc}"


def build_vscode_language_model_config(ollama_url: str, models: list[dict]) -> list[dict]:
    ollama_origin = _http_origin(ollama_url)
    configured_models = []
    for model in models:
        model_id = model.get("name")
        if model.get("installed") is not True or not isinstance(model_id, str) or not model_id:
            continue
        capabilities = set(model.get("capabilities") or ())
        context_window = model.get("context_length")
        if not isinstance(context_window, int) or context_window < 4096:
            context_window = 32768
        max_output_tokens = min(16384, max(2048, context_window // 8))
        configured_models.append({
            "id": model_id,
            "name": model_id,
            "url": f"{ollama_origin}/v1/chat/completions",
            "apiType": "chat-completions",
            "toolCalling": bool(model.get("tool_calling", "tools" in capabilities)),
            "vision": bool(model.get("vision", "vision" in capabilities)),
            "contextWindow": context_window,
            "maxInputTokens": context_window - max_output_tokens,
            "maxOutputTokens": max_output_tokens,
        })
    return [{
        "name": "JSON_CODR",
        "vendor": "customendpoint",
        "apiKey": "ollama",
        "apiType": "chat-completions",
        "models": configured_models,
    }]


def build_discovery_document(base_url: str, ollama_url: str) -> dict:
    from web_app.integrations.mcp_server import PROTOCOL_VERSION, TOOLS

    service_origin = _http_origin(base_url)
    ollama_origin = _http_origin(ollama_url)
    command = ["python", "-m", "web_app.integrations.mcp_server"]
    environment = {
        "JSON_CODR_URL": service_origin,
        "PYTHONPATH": "${JSON_CODR_ROOT}",
    }
    return {
        "schema_version": 1,
        "service": {
            "name": "JSON_CODR",
            "version": APP_VERSION,
            "base_url": service_origin,
        },
        "borg": {
            "transport": "http",
            "health_url": f"{service_origin}/api/health",
            "models_url": f"{service_origin}/api/models",
            "workspace_task_url": f"{service_origin}/api/workspace/tasks",
        },
        "mcp": {
            "transport": "stdio",
            "protocol_version": PROTOCOL_VERSION,
            "command": command,
            "environment": environment,
            "tools": [tool["name"] for tool in TOOLS],
            "requirements": ["Set JSON_CODR_ROOT to the JSON_CODR installation directory"],
        },
        "ollama": {
            "base_url": ollama_origin,
            "api": "native",
            "provides_borg_tools": False,
        },
        "configurations": {
            "vscode": {
                "language_models_url": f"{service_origin}/api/integrations/vscode/language-models",
                "servers": {
                    "json-codr-borg": {
                        "type": "stdio",
                        "command": command[0],
                        "args": command[1:],
                        "env": environment,
                    }
                }
            },
            "visual_studio": {
                "servers": {
                    "json-codr-borg": {
                        "type": "stdio",
                        "command": command[0],
                        "args": command[1:],
                        "env": environment,
                    }
                }
            },
            "generic_mcp": {
                "transport": "stdio",
                "command": command,
                "environment": environment,
            },
        },
    }
