from __future__ import annotations

from collections.abc import Mapping, Set

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext


class McpAdapter:
    def __init__(self, backend, *, allowed_tools: Set[str]) -> None:
        self._backend = backend
        self._allowed_tools = frozenset(allowed_tools)

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        operation = call.operation
        if operation == "discover":
            result = _bounded_discovery(await self._backend.discover())
            approval_state = "not_required"
        else:
            tool = call.arguments.get("tool")
            arguments = call.arguments.get("arguments", {})
            if not isinstance(tool, str) or ("*" not in self._allowed_tools and tool not in self._allowed_tools):
                raise PermissionError("MCP tool is not approved")
            if not isinstance(arguments, Mapping):
                raise ValueError("MCP tool arguments must be an object")
            result = await self._backend.invoke(tool, dict(arguments))
            approval_state = "approved"
        yield AdapterEvent(
            event_type=f"mcp.{operation}.completed",
            payload={
                **result,
                "route": "compatibility",
                "execution_route": "compatibility",
                "adapter": call.capability_id,
                "adapter_id": call.capability_id,
                "approval_state": approval_state,
            },
        )


def _bounded_discovery(result: Mapping) -> dict:
    raw_tools = result.get("tools", [])
    tools = raw_tools if isinstance(raw_tools, list) else []
    bounded = []
    description_truncated = False
    for tool in tools[:100]:
        if not isinstance(tool, Mapping):
            continue
        description = str(tool.get("description", ""))
        description_truncated = description_truncated or len(description) > 512
        bounded.append({
            "name": str(tool.get("name", ""))[:256],
            "description": description[:512],
        })
    server = result.get("server", {})
    bounded_server = {
        str(key)[:128]: str(value)[:512]
        for key, value in server.items()
    } if isinstance(server, Mapping) else {}
    return {
        "server": bounded_server,
        "tools": bounded,
        "tool_count": len(tools),
        "catalog_truncated": len(tools) > len(bounded) or description_truncated,
    }
