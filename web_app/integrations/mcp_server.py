from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping

from web_app.integrations.borg_client import BorgClient, BorgClientError
from web_app.version import APP_VERSION


PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "json_codr.health",
        "description": "Read the live JSON_CODR service status and version.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "json_codr.models",
        "description": "List models detected by the live JSON_CODR service.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "json_codr.run_workspace_task",
        "description": "Submit project work through the BORG workspace service and return its real task state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "minLength": 1},
                "project_root": {"type": "string", "minLength": 1},
                "prompt": {"type": "string", "minLength": 1},
                "model_selection": {"type": "string", "minLength": 1, "default": "auto"},
                "context_references": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["session_id", "project_root", "prompt"],
            "additionalProperties": False,
        },
    },
]


class McpServer:
    def __init__(self, client: BorgClient) -> None:
        self.client = client

    def handle(self, message: Mapping | object) -> dict | None:
        if not isinstance(message, Mapping) or not isinstance(message.get("method"), str):
            return self._error(message.get("id") if isinstance(message, Mapping) else None, -32600, "Invalid Request")
        request_id = message.get("id")
        method = message["method"]
        params = message.get("params", {})
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return self._result(request_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "json-codr-borg", "version": APP_VERSION},
            })
        if method == "tools/list":
            return self._result(request_id, {"tools": TOOLS})
        if method != "tools/call" or not isinstance(params, Mapping):
            return self._error(request_id, -32601, "Method not found")
        return self._call_tool(request_id, params)

    def _call_tool(self, request_id, params: Mapping) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {})
        tool = next((item for item in TOOLS if item["name"] == name), None)
        if tool is None or not isinstance(arguments, Mapping) or not self._valid_arguments(tool, arguments):
            return self._error(request_id, -32602, "Invalid tool name or arguments")
        try:
            if name == "json_codr.health":
                result = self.client.health()
            elif name == "json_codr.models":
                result = {"models": self.client.models()}
            else:
                result = self.client.run_workspace_task(**dict(arguments))
        except BorgClientError as error:
            return self._result(request_id, self._tool_result({"error": str(error)}, is_error=True))
        return self._result(request_id, self._tool_result(result))

    @staticmethod
    def _valid_arguments(tool: dict, arguments: Mapping) -> bool:
        schema = tool["inputSchema"]
        properties = schema["properties"]
        required = schema.get("required", [])
        if any(key not in properties for key in arguments):
            return False
        if any(key not in arguments for key in required):
            return False
        return all(McpServer._matches(properties[key], value) for key, value in arguments.items())

    @staticmethod
    def _matches(schema: dict, value: object) -> bool:
        if schema["type"] == "string":
            return isinstance(value, str) and len(value) >= schema.get("minLength", 0)
        if schema["type"] == "array":
            return isinstance(value, list) and all(isinstance(item, str) for item in value)
        return True

    @staticmethod
    def _tool_result(result: object, *, is_error: bool = False) -> dict:
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
            "isError": is_error,
        }

    @staticmethod
    def _result(request_id, result: object) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expose JSON_CODR BORG capabilities over MCP stdio")
    parser.add_argument("--base-url", default=os.environ.get("JSON_CODR_URL", "http://127.0.0.1:8874"))
    parser.add_argument("--timeout", type=float, default=30.0)
    options = parser.parse_args(argv)
    server = McpServer(BorgClient(options.base_url, options.timeout))
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = server.handle(message)
        except json.JSONDecodeError:
            response = McpServer._error(None, -32700, "Parse error")
        if response is not None:
            print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
