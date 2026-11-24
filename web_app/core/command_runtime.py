from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Mapping

from pydantic import Field

from web_app.core.contracts import FrozenContract
from web_app.core.verification_profiles import VerificationProfileStore, render_profile_arguments


class _WindowsJob:
    """Minimal Windows Job Object wrapper used to retain descendants after their parent exits."""

    def __init__(self, process_id: int) -> None:
        import ctypes
        from ctypes import wintypes

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError(ctypes.get_last_error(), "failed to create verifier job object")
        process_handle = self._kernel32.OpenProcess(0x0001 | 0x0100 | 0x0400, False, process_id)
        if not process_handle:
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "failed to open verifier process for job assignment")
        try:
            if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
                error = ctypes.get_last_error()
                self.close()
                raise OSError(error, "failed to assign verifier process to job object")
        finally:
            self._kernel32.CloseHandle(process_handle)

    def terminate(self) -> bool:
        return bool(self._handle and self._kernel32.TerminateJobObject(self._handle, 1))

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


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

    @property
    def profile_store_path(self) -> Path | None:
        return None if self._profiles is None else self._profiles.path

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
        argv = (
            profile.executable,
            *render_profile_arguments(profile, dict(values), project_root=project_root),
        )
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
        process_options: dict[str, object] = {}
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_options["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(
            *policy.argv, cwd=str(cwd), env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **process_options,
        )
        windows_job: _WindowsJob | None = None
        if os.name == "nt":
            try:
                windows_job = _WindowsJob(process.pid)
            except OSError as error:
                process.kill()
                await process.wait()
                raise RuntimeError("failed to establish verifier process-tree boundary") from error
        stdout = bytearray()
        stderr = bytearray()
        remaining = policy.max_output_bytes
        truncated = False
        output_lock = asyncio.Lock()

        async def consume(stream: asyncio.StreamReader, destination: bytearray) -> None:
            nonlocal remaining, truncated
            while chunk := await stream.read(65_536):
                async with output_lock:
                    keep = min(remaining, len(chunk))
                    if keep:
                        destination.extend(chunk[:keep])
                        remaining -= keep
                    if keep < len(chunk):
                        truncated = True

        readers = (
            asyncio.create_task(consume(process.stdout, stdout)),
            asyncio.create_task(consume(process.stderr, stderr)),
        )
        timed_out = False
        try:
            try:
                await asyncio.wait_for(
                    asyncio.gather(process.wait(), *readers),
                    policy.timeout_seconds,
                )
            except (TimeoutError, asyncio.TimeoutError):
                timed_out = True
                termination_error: RuntimeError | None = None
                try:
                    await self._terminate_process_tree(process, windows_job=windows_job)
                except RuntimeError as error:
                    termination_error = error
                try:
                    await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True), 5)
                except (TimeoutError, asyncio.TimeoutError):
                    for reader in readers:
                        reader.cancel()
                if termination_error is not None:
                    raise termination_error
        finally:
            if windows_job is not None:
                windows_job.close()
        redact = lambda value: self.SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value.decode("utf-8", errors="replace"))
        return CommandResult(
            argv=policy.argv, cwd=str(cwd), exit_code=-1 if timed_out else int(process.returncode or 0),
            stdout=redact(stdout), stderr=redact(stderr), timed_out=timed_out, truncated=truncated,
            isolation_level="output_bounded",
        )

    @staticmethod
    async def _terminate_process_tree(
        process: asyncio.subprocess.Process,
        *,
        windows_job: _WindowsJob | None = None,
    ) -> None:
        if os.name == "nt":
            terminated = windows_job is not None and windows_job.terminate()
            if not terminated:
                terminated = await CommandRuntime._taskkill_tree(process.pid)
            if not terminated:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise RuntimeError("failed to terminate verifier process tree")
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 5)
            except (TimeoutError, asyncio.TimeoutError):
                process.kill()
                await process.wait()

    @staticmethod
    async def _taskkill_tree(process_id: int) -> bool:
        try:
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            terminator = await asyncio.create_subprocess_exec(
                str(taskkill), "/PID", str(process_id), "/T", "/F",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return await asyncio.wait_for(terminator.wait(), 5) == 0
        except (FileNotFoundError, TimeoutError, asyncio.TimeoutError):
            return False
