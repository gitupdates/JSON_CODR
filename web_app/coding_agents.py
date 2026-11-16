from __future__ import annotations

import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


TOOLS = {"continue": "cn", "aider": "aider"}


@dataclass(frozen=True)
class CodingAgentGrant:
    id: str
    project_root: str
    tool: str
    scope: str
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CodingAgentLaunchPlan:
    tool: str
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]
    interactive: bool


class CodingAgentService:
    def __init__(self, data_root: Path, executable_finder: Callable[[str], str | None] = shutil.which) -> None:
        self.path = Path(data_root).resolve() / "coding-agent-grants.json"
        self.executable_finder = executable_finder

    @staticmethod
    def _project(path: Path | str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_dir():
            raise ValueError("Project root must be an existing directory")
        details = candidate.lstat()
        if candidate.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("Project root cannot be a reparse point")
        return candidate.resolve()

    @staticmethod
    def _tool(tool: str) -> str:
        normalized = tool.strip().lower()
        if normalized not in TOOLS:
            raise ValueError("Unsupported coding agent")
        return normalized

    def _read(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _write(self, grants: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".coding-agent-grants-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(grants, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def grant(self, project_root: Path | str, tool: str) -> CodingAgentGrant:
        project = str(self._project(project_root))
        normalized_tool = self._tool(tool)
        grants = self._read()
        now = datetime.now(timezone.utc).isoformat()
        existing = next((item for item in grants if item.get("project_root") == project and item.get("tool") == normalized_tool), None)
        if existing:
            existing.update({"scope": "full", "enabled": True, "updated_at": now})
            record = CodingAgentGrant(**existing)
        else:
            record = CodingAgentGrant(uuid.uuid4().hex, project, normalized_tool, "full", True, now, now)
            grants.append(asdict(record))
        self._write(grants)
        return record

    def revoke(self, grant_id: str) -> CodingAgentGrant:
        grants = self._read()
        target = next((item for item in grants if item.get("id") == grant_id), None)
        if target is None:
            raise KeyError(grant_id)
        target["enabled"] = False
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(grants)
        return CodingAgentGrant(**target)

    def authorized(self, working_directory: Path | str, tool: str) -> bool:
        try:
            working = self._project(working_directory)
            normalized_tool = self._tool(tool)
        except ValueError:
            return False
        for item in self._read():
            if not item.get("enabled") or item.get("tool") != normalized_tool:
                continue
            try:
                root = self._project(item.get("project_root", ""))
                working.relative_to(root)
                return True
            except (ValueError, TypeError):
                continue
        return False

    def status(self) -> dict:
        return {
            "tools": [{"id": tool, "executable": executable, "installed": bool(self.executable_finder(executable))}
                      for tool, executable in TOOLS.items()],
            "grants": self._read(),
        }

    def launch_plan(
        self,
        tool: str,
        working_directory: Path | str,
        model: str,
        mode: str,
        prompt: str | None = None,
    ) -> CodingAgentLaunchPlan:
        normalized_tool = self._tool(tool)
        working = self._project(working_directory)
        if not self.authorized(working, normalized_tool):
            raise PermissionError("Coding agent requires persistent authorization for this project and tool")
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", model):
            raise ValueError("Invalid model name")
        if mode not in {"interactive", "delegated"}:
            raise ValueError("Unsupported coding agent mode")
        if mode == "delegated" and not (prompt or "").strip():
            raise ValueError("Delegated mode requires a prompt")
        executable = self.executable_finder(TOOLS[normalized_tool])
        if not executable:
            raise RuntimeError(f"{TOOLS[normalized_tool]} is not installed")
        interactive = mode == "interactive"
        if normalized_tool == "continue":
            model_name = f"ollama/{model}"
            argv = (executable, "--model", model_name) if interactive else (
                executable, "-p", prompt.strip(), "--allow", "*", "--model", model_name
            )
            environment = {}
        else:
            model_name = f"ollama_chat/{model}"
            argv = (executable, "--model", model_name) if interactive else (
                executable, "--model", model_name, "--message", prompt.strip(), "--yes-always"
            )
            environment = {"OLLAMA_API_BASE": "http://127.0.0.1:11434"}
        return CodingAgentLaunchPlan(normalized_tool, argv, str(working), environment, interactive)
