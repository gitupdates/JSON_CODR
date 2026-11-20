from __future__ import annotations

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext


class AnalysisAdapter:
    def __init__(self, backend) -> None:
        self._backend = backend

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        tool = call.capability_id.split(".", 1)[0]
        if not await self._backend.available(tool):
            yield AdapterEvent(
                event_type=f"{tool}.unavailable",
                payload={"available": False, "reason": f"{tool} is unavailable"},
            )
            return
        target = call.arguments.get("target")
        if not isinstance(target, str):
            raise ValueError("analysis capability requires a target")
        result = await self._backend.run(tool, target)
        yield AdapterEvent(event_type=f"{tool}.completed", payload={"available": True, **result})
