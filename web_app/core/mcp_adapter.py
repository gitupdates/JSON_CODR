from __future__ import annotations

from collections.abc import Mapping, Set

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext


class McpAdapter:
    def __init__(self, backend, *, allowed_tools: Set[str], server_id: str | None = None) -> None:
        self._backend = backend
        self._allowed_tools = frozenset(allowed_tools)
        self.server_id = server_id

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        operation = call.capability_id.rsplit(".", 1)[-1]
        if operation == "discover":
            result = await self._backend.discover()
        else:
            tool = call.arguments.get("tool")
            arguments = call.arguments.get("arguments", {})
            if not isinstance(tool, str) or ("*" not in self._allowed_tools and tool not in self._allowed_tools):
                raise PermissionError("MCP tool is not approved")
            if not isinstance(arguments, Mapping):
                raise ValueError("MCP tool arguments must be an object")
            result = await self._backend.invoke(tool, dict(arguments))
        yield AdapterEvent(event_type=f"mcp.{operation}.completed", payload=result)
