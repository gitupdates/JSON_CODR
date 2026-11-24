from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path


class SidecarError(RuntimeError):
    pass


Runner = Callable[[list[str], dict, float], Awaitable[tuple[int, str, str]]]


class SidecarClient:
    def __init__(self, python: Path | None = None, runner: Runner | None = None) -> None:
        self.python = Path(python or sys.executable)
        self.runner = runner or self._run

    async def request(self, operation: str, payload: dict, timeout: float = 300) -> dict:
        request = {"operation": operation, "payload": payload}
        command = [str(self.python), "-m", "web_app.inference.sidecar_main"]
        try:
            returncode, stdout, stderr = await self.runner(command, request, timeout)
        except asyncio.TimeoutError as error:
            raise SidecarError("Connector request timed out") from error
        if returncode:
            raise SidecarError(stderr.strip() or f"Connector exited with code {returncode}")
        try:
            response = json.loads(stdout.strip())
        except json.JSONDecodeError as error:
            raise SidecarError("Connector returned invalid JSON") from error
        if not response.get("ok"):
            raise SidecarError(response.get("error") or "Connector request failed")
        return response.get("result", {})

    @staticmethod
    async def _run(command: list[str], request: dict, timeout: float) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate((json.dumps(request) + "\n").encode()), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
