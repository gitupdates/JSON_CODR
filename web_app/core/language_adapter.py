from __future__ import annotations

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext


class LanguageAdapter:
    def __init__(self, backend) -> None:
        self._backend = backend

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        path = call.arguments.get("path")
        if not isinstance(path, str):
            raise ValueError("language capability requires a path")
        operation = call.capability_id.rsplit(".", 1)[-1]
        handler = getattr(self._backend, operation)
        try:
            result = await handler(path)
        except RuntimeError:
            result = await self._backend.parse(path)
        yield AdapterEvent(event_type=f"{call.capability_id}.completed", payload=result)
