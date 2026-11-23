from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from web_app.integrations.mcp_server import McpServer


ServerFactory = Callable[[Request], McpServer]


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.casefold() == "localhost"


def create_mcp_http_router(server_factory: ServerFactory, *, loopback_only: bool = True) -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def handle_mcp(request: Request) -> Response:
        if loopback_only and not _is_loopback(request.client.host if request.client else None):
            return Response(status_code=403)
        if request.headers.get("mcp-session-id"):
            return Response(status_code=404)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().casefold() != "application/json":
            return Response(status_code=415)
        try:
            message = await request.json()
        except ValueError:
            return JSONResponse(McpServer._error(None, -32700, "Parse error"), status_code=400)
        result = await asyncio.to_thread(server_factory(request).handle, message)
        if result is None:
            return Response(status_code=202)
        return JSONResponse(result)

    return router
