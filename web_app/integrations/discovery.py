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
