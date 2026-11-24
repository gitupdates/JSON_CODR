from __future__ import annotations

import inspect
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from web_app.core.connection_recovery import (
    ConnectionDescriptor,
    ConnectionState,
    ConnectionStatus,
    RecoveryAction,
    RecoveryActionClass,
    RecoveryActionResult,
    RecoveryPlan,
)


@dataclass(frozen=True)
class ProgramConnectionSpec:
    connection_id: str
    display_name: str
    kind: str
    credential_mode: str
    capabilities: tuple[str, ...]
    config_paths: tuple[Path, ...]
    generated_config: dict


class FileConnectionAdapter:
    def __init__(self, spec: ProgramConnectionSpec, *, functional_probe: Callable[[], object]):
        self.spec = spec
        self.descriptor = ConnectionDescriptor(
            connection_id=spec.connection_id,
            display_name=spec.display_name,
            kind=spec.kind,
            credential_mode=spec.credential_mode,
            capabilities=spec.capabilities,
        )
        self._functional_probe = functional_probe

    @property
    def target(self) -> Path:
        return self.spec.config_paths[0]

    @property
    def backup(self) -> Path:
        return self.target.with_name(f"{self.target.name}.json-codr.bak")

    async def describe(self) -> ConnectionDescriptor:
        return self.descriptor

    async def _probe_function(self) -> bool:
        result = self._functional_probe()
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    async def probe(self) -> ConnectionStatus:
        target = next((path for path in self.spec.config_paths if path.is_file()), None)
        if target is None:
            return self._status(ConnectionState.unavailable, False, "config_missing")
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return self._status(ConnectionState.degraded, False, "config_malformed", str(error))
        functional = await self._probe_function()
        return self._status(
            ConnectionState.ready if functional else ConnectionState.degraded,
            functional,
            "ready" if functional else "functional_probe_failed",
        )

    async def plan(self, status: ConnectionStatus) -> RecoveryPlan:
        actions = [RecoveryAction("configure", "Configure", RecoveryActionClass.approval_required)]
        if self.target.exists():
            actions.extend((
                RecoveryAction("disable", "Disable", RecoveryActionClass.approval_required),
                RecoveryAction("remove", "Remove", RecoveryActionClass.approval_required),
            ))
        if self.backup.exists():
            actions.append(RecoveryAction("restore", "Restore backup", RecoveryActionClass.approval_required))
        return RecoveryPlan(self.spec.connection_id, "connections-v1", tuple(actions))

    async def preview(self, action_id: str) -> dict:
        before = {"status": "missing", "keys": []}
        if self.target.is_file():
            try:
                existing = json.loads(self.target.read_text(encoding="utf-8"))
                before = {
                    "status": "valid",
                    "keys": sorted(existing) if isinstance(existing, dict) else [],
                }
            except (OSError, UnicodeError, json.JSONDecodeError):
                before = {"status": "malformed; preserved until approved", "keys": []}
        after = {
            "status": "generated" if action_id == "configure" else "removed",
            "keys": sorted(self.spec.generated_config) if action_id == "configure" else [],
        }
        return {
            "action_id": action_id,
            "target_name": self.target.name,
            "target_parent": self.target.parent.name,
            "before": before,
            "after": after,
        }

    async def recover(self, action_ids: frozenset[str]) -> tuple[RecoveryActionResult, ...]:
        results = []
        for action_id in sorted(action_ids):
            if action_id == "configure":
                self._backup_current()
                self._write_json(self.spec.generated_config)
            elif action_id in {"disable", "remove"}:
                self._backup_current()
                self.target.unlink(missing_ok=True)
            elif action_id == "restore":
                if not self.backup.is_file():
                    raise FileNotFoundError(f"backup not found: {self.backup}")
                self.target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.backup, self.target)
            else:
                raise ValueError(f"unknown connection action: {action_id}")
            results.append(RecoveryActionResult(action_id, "completed", str(self.target)))
        return tuple(results)

    async def verify(self) -> ConnectionStatus:
        return await self.probe()

    def _backup_current(self) -> None:
        if self.target.is_file() and not self.backup.exists():
            self.backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.target, self.backup)

    def _write_json(self, value: dict) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.target.with_name(f".{self.target.name}.tmp")
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.target)

    def _status(
        self,
        state: ConnectionState,
        functional_probe: bool,
        diagnostic_code: str,
        detail: str | None = None,
    ) -> ConnectionStatus:
        return ConnectionStatus(self.spec.connection_id, state, functional_probe, diagnostic_code, detail)


def build_program_connection_adapters(
    *,
    data_root: Path,
    service_url: str,
    functional_probe: Callable[[], object],
    home: Path | None = None,
    appdata: Path | None = None,
    localappdata: Path | None = None,
) -> tuple[FileConnectionAdapter, ...]:
    home = Path(home or Path.home())
    appdata = Path(appdata or os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    localappdata = Path(localappdata or os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    endpoint = f"{service_url.rstrip('/')}/mcp"
    openai_endpoint = f"{service_url.rstrip('/')}/v1"
    http_server = {"type": "http", "url": endpoint}
    specs = (
        ProgramConnectionSpec(
            "vscode:copilot", "VS Code / Copilot", "mcp", "none", ("tools", "models"),
            (appdata / "Code" / "User" / "mcp.json",), {"servers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "visualstudio:2022", "Visual Studio 2022", "mcp", "none", ("tools",),
            (localappdata / "JSON_CODR" / "visual-studio-2022.mcp.json",),
            {"inputs": [], "servers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "codex:plugin", "Codex", "plugin", "native", ("tools", "skills"),
            (home / ".codex" / "plugins" / "json-codr" / "mcp.json",),
            {"mcpServers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "claude:desktop", "Claude Desktop", "mcp", "none", ("tools",),
            (appdata / "Claude" / "claude_desktop_config.json",),
            {"mcpServers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "cursor:global", "Cursor", "mcp", "none", ("tools",),
            (home / ".cursor" / "mcp.json",), {"mcpServers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "windsurf:global", "Windsurf", "mcp", "none", ("tools",),
            (home / ".codeium" / "windsurf" / "mcp_config.json",),
            {"mcpServers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "ollama:native", "Ollama", "native", "none", ("inference", "models"),
            (data_root / "connections" / "ollama.json",),
            {"host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")},
        ),
        ProgramConnectionSpec(
            "generic:mcp", "Generic MCP client", "mcp", "none", ("tools",),
            (data_root / "connections" / "generic-mcp.json",),
            {"mcpServers": {"json-codr": http_server}},
        ),
        ProgramConnectionSpec(
            "generic:openai", "Generic OpenAI-compatible client", "openai", "per-user", ("chat", "models"),
            (data_root / "connections" / "generic-openai.json",),
            {"base_url": openai_endpoint, "api_key": "use-user-credential-store"},
        ),
    )
    return tuple(FileConnectionAdapter(spec, functional_probe=functional_probe) for spec in specs)
