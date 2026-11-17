from __future__ import annotations

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
        shell = str(call.arguments.get("shell", "powershell"))
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
