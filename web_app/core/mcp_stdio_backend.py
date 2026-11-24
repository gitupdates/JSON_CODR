from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
from typing import Any

from web_app.version import APP_VERSION


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    allowed_tools: frozenset[str] = frozenset()
    transport: str = "stdio"
    startup_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 450.0
    max_frame_bytes: int = 16 * 1024 * 1024
    inherit_environment: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("MCP server name is required")
        if not self.command.strip():
            raise ValueError("MCP server command is required")
        if self.transport != "stdio":
            raise ValueError(f"unsupported MCP transport: {self.transport}")
        if self.max_frame_bytes < 65536:
            raise ValueError("MCP max frame size must be at least 65536 bytes")


def load_mcp_server_configs(path: Path) -> tuple[McpServerConfig, ...]:
    path = Path(path)
    if not path.is_file():
        return ()
    document = json.loads(path.read_text(encoding="utf-8"))
    servers = document.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError("MCP configuration must contain an mcpServers object")
    configs: list[McpServerConfig] = []
    for name, value in servers.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("MCP server entries must be named objects")
        args = value.get("args", [])
        env = value.get("env", {})
        allowed = value.get("allowedTools", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError(f"MCP server {name} args must be strings")
        if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in env.items()):
            raise ValueError(f"MCP server {name} env must contain string values")
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise ValueError(f"MCP server {name} allowedTools must be strings")
        configs.append(McpServerConfig(
            name=name,
            command=str(value.get("command", "")),
            args=tuple(args),
            env=dict(env),
            allowed_tools=frozenset(allowed),
            transport=str(value.get("transport", "stdio")),
            startup_timeout_seconds=float(value.get("startupTimeoutSeconds", 30)),
            tool_timeout_seconds=float(value.get("toolTimeoutSeconds", 450)),
            max_frame_bytes=int(value.get("maxFrameBytes", 16 * 1024 * 1024)),
        ))
    return tuple(configs)


def build_mcp_adapters(
    path: Path,
    *,
    rea_provider_root: Path | None = None,
    craft_command: tuple[str, ...] | None = None,
):
    from web_app.core.mcp_adapter import McpAdapter

    adapters = {}
    backends = []
    configs = list(load_mcp_server_configs(path))
    if rea_provider_root is not None and not any(config.name == "rea" for config in configs):
        configs.append(McpServerConfig(name="rea", command="managed", allowed_tools=frozenset({"*"})))
    if craft_command:
        command, *base_args = craft_command
        configured = {config.name for config in configs}
        for name, mode in (("craft-clean-room", "--clean-room"), ("craft-deep", "--deep")):
            if name not in configured:
                configs.append(McpServerConfig(
                    name=name,
                    command=command,
                    args=(*base_args, mode, "mcp"),
                    allowed_tools=frozenset({"*"}),
                    startup_timeout_seconds=60,
                    tool_timeout_seconds=900,
                ))
    for config in configs:
        if config.name == "rea" and rea_provider_root is not None and (Path(rea_provider_root) / "state.sqlite").is_file():
            backend = LeasedReaBackend(Path(rea_provider_root), config)
            adapter = McpAdapter(backend, allowed_tools=config.allowed_tools or frozenset({"*"}))
            adapters["mcp.rea.discover"] = adapter
            adapters["mcp.rea.invoke"] = adapter
            backends.append(backend)
            continue
        if config.name == "rea" and rea_provider_root is not None:
            config = _active_rea_config(config, Path(rea_provider_root))
        backend = StdioMcpBackend(config)
        adapter = McpAdapter(backend, allowed_tools=config.allowed_tools)
        adapters[f"mcp.{config.name}.discover"] = adapter
        adapters[f"mcp.{config.name}.invoke"] = adapter
        backends.append(backend)
    return adapters, tuple(backends)


def _active_rea_config(fallback: McpServerConfig, provider_root: Path) -> McpServerConfig:
    active_path = provider_root / "active.json"
    if not active_path.is_file():
        return fallback
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        version = str(active["version"])
        versions_root = (provider_root / "versions").resolve()
        script = (
            versions_root / version / "installation" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        ).resolve()
        script.relative_to(versions_root)
        node = shutil.which("node")
        if node is None or not script.is_file():
            return fallback
        return replace(fallback, command=node, args=(str(script), "mcp"))
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return fallback


class StdioMcpBackend:
    protocol_version = "2025-06-18"

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._request_id = 0
        self._server_info: dict[str, Any] = {}
        self._stderr: list[str] = []

    async def discover(self) -> dict[str, Any]:
        await self._ensure_started()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = await self._request("tools/list", params, self.config.tool_timeout_seconds)
            page = result.get("tools", [])
            if not isinstance(page, list):
                raise RuntimeError(f"MCP server {self.config.name} returned an invalid tools list")
            tools.extend(item for item in page if isinstance(item, dict))
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(f"MCP server {self.config.name} repeated a pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return {"server": dict(self._server_info), "tools": tools}

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if "*" not in self.config.allowed_tools and name not in self.config.allowed_tools:
            raise PermissionError(f"MCP tool is not approved: {name}")
        await self._ensure_started()
        return await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            self.config.tool_timeout_seconds,
        )

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task is not None),
            return_exceptions=True,
        )
        self._reader_task = None
        self._stderr_task = None
        self._fail_pending(RuntimeError(f"MCP server {self.config.name} closed"))

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        async with self._start_lock:
            if self._process is not None and self._process.returncode is None:
                return
            environment = os.environ.copy() if self.config.inherit_environment else {
                key: value for key, value in os.environ.items()
                if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
            }
            environment.update(self.config.env)
            self._process = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                limit=self.config.max_frame_bytes,
            )
            self._reader_task = asyncio.create_task(self._read_stdout())
            self._stderr_task = asyncio.create_task(self._read_stderr())
            try:
                initialized = await self._request_without_start(
                    "initialize",
                    {
                        "protocolVersion": self.protocol_version,
                        "capabilities": {},
                        "clientInfo": {"name": "JSON_CODR", "version": APP_VERSION},
                    },
                    self.config.startup_timeout_seconds,
                )
                server_info = initialized.get("serverInfo", {})
                self._server_info = dict(server_info) if isinstance(server_info, dict) else {}
                await self._notify("notifications/initialized", {})
            except BaseException:
                await self.close()
                raise

    async def _request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        await self._ensure_started()
        return await self._request_without_start(method, params, timeout)

    async def _request_without_start(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise RuntimeError(self._failure_message("is not running"))
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        async with self._write_lock:
            process.stdin.write(encoded)
            await process.stdin.drain()

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int) and request_id in self._pending:
                    future = self._pending[request_id]
                    if "error" in message:
                        error = message["error"]
                        future.set_exception(RuntimeError(f"MCP {self.config.name} error: {error}"))
                    else:
                        result = message.get("result", {})
                        if isinstance(result, dict):
                            future.set_result(result)
                        else:
                            future.set_exception(RuntimeError(f"MCP {self.config.name} returned a non-object result"))
        except asyncio.CancelledError:
            raise
        finally:
            if self._process is process and process.returncode is None:
                await process.wait()
            self._fail_pending(RuntimeError(self._failure_message("stopped before replying")))

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while line := await process.stderr.readline():
                self._stderr.append(line.decode("utf-8", errors="replace").rstrip())
                del self._stderr[:-50]
        except asyncio.CancelledError:
            raise

    def _failure_message(self, suffix: str) -> str:
        detail = f": {self._stderr[-1]}" if self._stderr else ""
        return f"MCP server {self.config.name} {suffix}{detail}"

    def _fail_pending(self, error: BaseException) -> None:
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)


class LeasedReaBackend:
    def __init__(self, provider_root: Path, fallback: McpServerConfig) -> None:
        self.provider_root = provider_root.resolve()
        self.fallback = fallback
        self._backend: StdioMcpBackend | None = None
        self._store = None
        self._lease = None
        self._lifecycle_lock = asyncio.Lock()

    async def discover(self) -> dict[str, Any]:
        backend = await self._ensure_backend()
        return await backend.discover()

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        backend = await self._ensure_backend()
        return await backend.invoke(name, arguments)

    async def close(self) -> None:
        async with self._lifecycle_lock:
            backend, store, lease = self._backend, self._store, self._lease
            self._backend = None
            self._store = None
            self._lease = None
            if backend is not None:
                await backend.close()
            if store is not None:
                try:
                    if lease is not None:
                        store.release_lease(lease.lease_id)
                finally:
                    store.close()

    async def _ensure_backend(self) -> StdioMcpBackend:
        from web_app.core.rea_provider_state import ReaProviderStore

        if self._backend is not None:
            return self._backend
        async with self._lifecycle_lock:
            if self._backend is not None:
                return self._backend
            store = ReaProviderStore(self.provider_root / "state.sqlite")
            lease = store.acquire_lease(f"mcp:{id(self)}")
            active = store.active()
            if active is None or active.generation != lease.generation or active.version != lease.version:
                store.release_lease(lease.lease_id)
                store.close()
                raise RuntimeError("REA activation changed while acquiring a runtime lease")
            try:
                config = _versioned_rea_config(self.fallback, self.provider_root, lease.version)
                backend = StdioMcpBackend(config)
            except BaseException:
                store.release_lease(lease.lease_id)
                store.close()
                raise
            self._store = store
            self._lease = lease
            self._backend = backend
            return backend


def _versioned_rea_config(fallback: McpServerConfig, provider_root: Path, version: str) -> McpServerConfig:
    versions_root = (provider_root / "versions").resolve()
    script = (versions_root / version / "installation" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs").resolve()
    script.relative_to(versions_root)
    node = shutil.which("node")
    if node is None or not script.is_file():
        raise RuntimeError(f"active REA {version} has no launchable runtime")
    return replace(fallback, command=node, args=(str(script), "mcp"), inherit_environment=False)
