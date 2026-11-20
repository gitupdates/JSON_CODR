from __future__ import annotations

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext


class BrowserAdapter:
    def __init__(self, backend) -> None:
        self._backend = backend

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        operation = call.capability_id.rsplit(".", 1)[-1]
        handler = getattr(self._backend, operation)
        if operation == "inspect":
            result = await handler(call.arguments.get("url"))
        else:
            result = await handler(dict(call.arguments))
        yield AdapterEvent(event_type=f"browser.{operation}.completed", payload=result)
