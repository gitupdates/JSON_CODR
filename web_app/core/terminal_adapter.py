from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
from web_app.core.contracts import FrozenContract, TaskId


class TerminalSessionRecord(FrozenContract):
    terminal_id: str
    task_id: TaskId
    pid: int
    shell: str
    cwd: str
    last_sequence: int = 0


class TerminalAdapter:
    def __init__(self, terminal_service) -> None:
        self._terminal = terminal_service
        self._sessions: dict[str, TerminalSessionRecord] = {}
        self._history: dict[str, list[str]] = defaultdict(list)

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        if call.capability_id in {"terminal.interrupt", "terminal.close"}:
            terminal_id = call.arguments.get("terminal_id")
            if not isinstance(terminal_id, str) or not terminal_id:
                raise ValueError("terminal mutation requires a terminal identity")
            if call.capability_id == "terminal.interrupt":
                self._terminal.interrupt(terminal_id)
                yield AdapterEvent(event_type="terminal.interrupted", payload={"terminal_id": terminal_id})
            else:
                self._terminal.close(terminal_id)
                yield AdapterEvent(event_type="terminal.closed", payload={"terminal_id": terminal_id})
            return
        shell = str(call.arguments.get("shell", "powershell"))
        if call.capability_id == "terminal.session":
            record = self._terminal.create(shell, Path(call.project_root))
            session = TerminalSessionRecord(
                terminal_id=record.id,
                task_id=context.task_id,
                pid=record.pid,
                shell=record.shell,
                cwd=record.cwd,
            )
            self._sessions[record.id] = session
            payload = {
                "id": record.id,
                "pid": record.pid,
                "shell": record.shell,
                "cwd": record.cwd,
                "status": record.status,
            }
            for optional in ("external", "backend"):
                if hasattr(record, optional):
                    payload[optional] = getattr(record, optional)
            yield AdapterEvent(event_type="terminal.session_started", payload={"record": payload, "task_id": context.task_id})
            return
        command = call.arguments.get("command")
        if not isinstance(command, str) or not command:
            raise ValueError("terminal execution requires a command")
        record = self._terminal.create(shell, Path(call.project_root))
        session = TerminalSessionRecord(
            terminal_id=record.id,
            task_id=context.task_id,
            pid=record.pid,
            shell=record.shell,
            cwd=record.cwd,
        )
        self._sessions[record.id] = session
        self._history[record.id].append(command)
        yield AdapterEvent(event_type="terminal.started", payload={"terminal_id": record.id, "task_id": context.task_id, "pid": record.pid})
        self._terminal.write(record.id, command + "\r\n")
        chunks = self._terminal.read_after(record.id, 0)
        for sequence, output in chunks:
            self._sessions[record.id] = session.model_copy(update={"last_sequence": sequence})
            yield AdapterEvent(event_type="terminal.output", payload={"terminal_id": record.id, "sequence": sequence, "output": output})

    def cancel(self, terminal_id: str) -> None:
        self._terminal.close(terminal_id)

    def history(self, terminal_id: str) -> tuple[str, ...]:
        return tuple(self._history.get(terminal_id, ()))

    async def run_bounded(self, command: str, cwd: Path, shell: str, timeout: int) -> dict[str, object]:
        if sys.platform == "win32":
            executable = "powershell.exe" if shell == "powershell" else "cmd.exe"
            arguments = ["-NoProfile", "-NonInteractive", "-Command", command] if shell == "powershell" else ["/d", "/s", "/c", command]
        else:
            executable = os.environ.get("SHELL", "/bin/sh")
            arguments = ["-c", command]
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            process.kill()
            await process.wait()
            return {"exit_code": -1, "stdout": "", "stderr": f"Execution timed out after {timeout}s", "timed_out": True}
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        return {
            "exit_code": int(process.returncode or 0),
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "timed_out": False,
        }
