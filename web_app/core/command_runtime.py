from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Mapping

from pydantic import Field

from web_app.core.contracts import FrozenContract
from web_app.core.verification_profiles import VerificationProfileStore, render_profile_arguments


class CommandPolicy(FrozenContract):
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_output_bytes: int = Field(default=1_048_576, ge=1024, le=8_388_608)
    network_approved: bool = False
    environment: dict[str, str] = Field(default_factory=dict)


class CommandResult(FrozenContract):
    argv: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    isolation_level: str


class CommandRuntime:
    SAFE_ENVIRONMENT = frozenset({"SystemRoot", "SYSTEMROOT", "WINDIR", "windir", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP"})
    SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key)=([^\s]+)")

    def __init__(self, profiles: VerificationProfileStore | None = None) -> None:
        self._profiles = profiles

    async def run_interactive_admin(
        self,
        policy: CommandPolicy,
        *,
        project_root: str | Path,
        administrator_scopes: tuple[str, ...],
    ) -> CommandResult:
        """Run an administrator-approved, interactive command without claiming isolation."""
        if "terminal.write" not in administrator_scopes:
            raise PermissionError("interactive command execution requires an administrator terminal scope")
        return await self._run(policy, project_root=project_root)

    async def run_profile(
        self,
        *,
        profile_id: str,
        values: Mapping[str, object],
        project_root: str | Path,
        environment: Mapping[str, str] | None = None,
        raw_argv: tuple[str, ...] | None = None,
    ) -> CommandResult:
        if raw_argv is not None:
            raise ValueError("raw argv is only available to interactive administrators")
        if environment:
            raise ValueError("profile execution does not accept environment overrides")
        if self._profiles is None:
            raise RuntimeError("verification profile store is not configured")
        profile = self._profiles.resolve(profile_id)
        if profile.network_policy == "deny":
            raise ValueError("no-network profiles require an enforcing sandbox adapter")
        argv = (profile.executable, *render_profile_arguments(profile, dict(values)))
        return await self._run(CommandPolicy(
            argv=argv,
            cwd="." if profile.cwd_rule == "project_root" else profile.cwd_rule,
            timeout_seconds=profile.timeout_seconds,
            max_output_bytes=profile.max_output_bytes,
        ), project_root=project_root)

    async def _run(self, policy: CommandPolicy, *, project_root: str | Path) -> CommandResult:
        root = Path(project_root).resolve(strict=True)
        cwd = Path(policy.cwd)
        cwd = cwd.resolve() if cwd.is_absolute() else (root / cwd).resolve()
        if not cwd.is_dir() or not cwd.is_relative_to(root):
            raise ValueError("command cwd escapes the registered project")
        if any("\x00" in value or "\n" in value or "\r" in value for value in policy.argv):
            raise ValueError("command arguments contain control characters")
        environment = {key: value for key, value in os.environ.items() if key in self.SAFE_ENVIRONMENT}
        for key, value in policy.environment.items():
            if key not in self.SAFE_ENVIRONMENT:
                raise ValueError(f"environment key is not allowed: {key}")
            environment[key] = value
        process = await asyncio.create_subprocess_exec(
            *policy.argv, cwd=str(cwd), env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), policy.timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError):
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
        limit = policy.max_output_bytes
        truncated = len(stdout) + len(stderr) > limit
        stdout = stdout[:limit]
        stderr = stderr[: max(0, limit - len(stdout))]
        redact = lambda value: self.SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value.decode("utf-8", errors="replace"))
        return CommandResult(
            argv=policy.argv, cwd=str(cwd), exit_code=-1 if timed_out else int(process.returncode or 0),
            stdout=redact(stdout), stderr=redact(stderr), timed_out=timed_out, truncated=truncated,
            isolation_level="windows_process_constrained" if os.name == "nt" else "process_constrained",
        )
