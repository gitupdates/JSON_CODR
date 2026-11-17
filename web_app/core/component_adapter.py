from __future__ import annotations

import asyncio

from web_app.core.adapters import AdapterEvent, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.component_catalog import ComponentCatalog
from web_app.core.component_registry import ComponentRegistry


class ComponentExecutionAdapter:
    def __init__(self, registry: ComponentRegistry, catalog: ComponentCatalog) -> None:
        self.registry, self.catalog = registry, catalog

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        component_id = str(call.arguments.get("component_id", ""))
        command = str(call.arguments.get("command", call.operation))
        component = next((item for item in self.catalog.resolve_components(context.project_id) if item.component_id == component_id), None)
        if component is None or command not in component.commands:
            raise CapabilityExecutionError("component_unavailable", "verified component command is unavailable")
        lease = self.registry.acquire_lease(component_id, context.project_id)
        try:
            process = await asyncio.create_subprocess_exec(*component.commands[command], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            output, _ = await process.communicate()
            if process.returncode:
                raise CapabilityExecutionError("component_failed", "component command failed")
            yield AdapterEvent(event_type="component.output", payload={"component_id": component_id, "generation": component.generation, "output": output.decode("utf-8", errors="replace")})
        finally:
            self.registry.release_lease(lease.lease_id)
