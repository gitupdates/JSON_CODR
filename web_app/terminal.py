import os
import queue
import signal
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


def child_environment(overrides: dict[str, str] | None = None, inherited=None) -> dict[str, str]:
    environment = dict(os.environ if inherited is None else inherited)
    system_root = environment.get("SystemRoot") or environment.get("SYSTEMROOT")
    if system_root and not (environment.get("windir") or environment.get("WINDIR")):
        environment["windir"] = system_root
    environment.update(overrides or {})
    return environment


@dataclass
class TerminalRecord:
    id: str
    pid: int
    shell: str
    cwd: str
    status: str = "running"
    external: bool = False
    backend: str = "pipe"


class _PtyProcess(Protocol):
    pid: int

    def read(self) -> str: ...
    def write(self, data: str) -> None: ...
    def setwinsize(self, rows: int, cols: int) -> None: ...
    def sendintr(self) -> None: ...
    def isalive(self) -> bool: ...
    def close(self, force: bool = False) -> None: ...


PtyFactory = Callable[[list[str], str, dict[str, str], tuple[int, int]], _PtyProcess]
_AUTO_PTY = object()


def _default_pty_factory() -> PtyFactory | None:
    try:
        from winpty import PtyProcess
    except ImportError:
        return None

    def spawn(argv: list[str], cwd: str, env: dict[str, str], dimensions: tuple[int, int]):
        return PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=dimensions)

    return spawn


@dataclass
class _TerminalProcess:
    record: TerminalRecord
    process: object
    output: queue.Queue[str]
    history: deque[tuple[int, str]]
    condition: threading.Condition
    history_size: int = 0
    next_sequence: int = 1


class TerminalService:
    def __init__(
        self,
        pty_factory: PtyFactory | None | object = _AUTO_PTY,
        replay_limit: int = 4 * 1024 * 1024,
    ) -> None:
        self._terminals: dict[str, _TerminalProcess] = {}
        self._lock = threading.Lock()
        self._pty_factory = _default_pty_factory() if pty_factory is _AUTO_PTY else pty_factory
        self._replay_limit = replay_limit

    def create(self, shell: str, cwd: Path, cols: int = 100, rows: int = 30) -> TerminalRecord:
        if shell not in {"powershell", "cmd"}:
            raise ValueError("Unsupported shell")
        working_directory = Path(cwd).resolve()
        if not working_directory.is_dir():
            raise ValueError("Working directory does not exist")
        pipe_command = (
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NoExit", "-Command", "-"]
            if shell == "powershell"
            else ["cmd.exe", "/Q"]
        )
        environment = child_environment()
        if self._pty_factory is not None:
            pty_command = (
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NoExit"]
                if shell == "powershell"
                else pipe_command
            )
            return self._create_pty(pty_command, shell, str(working_directory), environment, rows, cols)
        process = subprocess.Popen(
            pipe_command,
            cwd=working_directory,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        record = TerminalRecord(uuid.uuid4().hex, process.pid, shell, str(working_directory))
        terminal = self._new_terminal(record, process)
        self._register(terminal)
        threading.Thread(target=self._read_pipe_output, args=(terminal,), daemon=True).start()
        return record

    def create_agent(self, plan) -> TerminalRecord:
        environment = child_environment(plan.environment)
        if plan.interactive:
            agent_command = list(plan.argv)
            if Path(plan.argv[0]).suffix.lower() in {".cmd", ".bat"}:
                command_processor = environment.get("COMSPEC") or str(
                    Path(environment["SystemRoot"]) / "System32" / "cmd.exe"
                )
                agent_command = [command_processor, "/d", "/s", "/c", subprocess.list2cmdline(plan.argv)]
            if self._pty_factory is not None:
                return self._create_pty(agent_command, plan.tool, plan.cwd, environment, 30, 100)
            process = subprocess.Popen(
                agent_command,
                cwd=plan.cwd,
                env=environment,
                creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            return TerminalRecord(
                uuid.uuid4().hex, process.pid, f"{plan.tool} · native console", plan.cwd, "external", True
            )
        process = subprocess.Popen(
            list(plan.argv),
            cwd=plan.cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        record = TerminalRecord(uuid.uuid4().hex, process.pid, plan.tool, plan.cwd)
        terminal = self._new_terminal(record, process)
        self._register(terminal)
        threading.Thread(target=self._read_pipe_output, args=(terminal,), daemon=True).start()
        return record

    def _create_pty(
        self,
        command: list[str],
        shell: str,
        cwd: str,
        environment: dict[str, str],
        rows: int,
        cols: int,
    ) -> TerminalRecord:
        assert self._pty_factory is not None
        process = self._pty_factory(command, cwd, environment, (rows, cols))
        record = TerminalRecord(uuid.uuid4().hex, process.pid, shell, cwd, backend="conpty")
        terminal = self._new_terminal(record, process)
        self._register(terminal)
        threading.Thread(target=self._read_pty_output, args=(terminal,), daemon=True).start()
        return record

    @staticmethod
    def _new_terminal(record: TerminalRecord, process: object) -> _TerminalProcess:
        return _TerminalProcess(record, process, queue.Queue(maxsize=2048), deque(), threading.Condition())

    def _register(self, terminal: _TerminalProcess) -> None:
        with self._lock:
            self._terminals[terminal.record.id] = terminal

    def _read_pipe_output(self, terminal: _TerminalProcess) -> None:
        assert terminal.process.stdout is not None
        while True:
            chunk = terminal.process.stdout.read1(256)
            if not chunk:
                break
            self._record_output(terminal, chunk.decode("utf-8", errors="replace"))
        self._mark_closed(terminal)

    def _read_pty_output(self, terminal: _TerminalProcess) -> None:
        while terminal.record.status == "running":
            try:
                text = terminal.process.read()
            except (EOFError, OSError):
                break
            if text:
                self._record_output(terminal, text)
        self._mark_closed(terminal)

    def _record_output(self, terminal: _TerminalProcess, text: str) -> None:
        try:
            terminal.output.put_nowait(text)
        except queue.Full:
            try:
                terminal.output.get_nowait()
            except queue.Empty:
                pass
            terminal.output.put_nowait("\n[output truncated]\n" + text)
        with terminal.condition:
            terminal.history.append((terminal.next_sequence, text))
            terminal.next_sequence += 1
            terminal.history_size += len(text.encode("utf-8"))
            while terminal.history and terminal.history_size > self._replay_limit:
                _, removed = terminal.history.popleft()
                terminal.history_size -= len(removed.encode("utf-8"))
            terminal.condition.notify_all()

    @staticmethod
    def _mark_closed(terminal: _TerminalProcess) -> None:
        terminal.record.status = "closed"
        with terminal.condition:
            terminal.condition.notify_all()

    def get(self, terminal_id: str) -> TerminalRecord:
        return self._lookup(terminal_id).record

    def list(self) -> list[TerminalRecord]:
        with self._lock:
            return [terminal.record for terminal in self._terminals.values()]

    def write(self, terminal_id: str, data: str) -> None:
        terminal = self._lookup(terminal_id)
        if terminal.record.status != "running":
            raise RuntimeError("Terminal is closed")
        if terminal.record.backend == "conpty":
            terminal.process.write(data)
            return
        if terminal.process.stdin is None:
            raise RuntimeError("Terminal input is unavailable")
        terminal.process.stdin.write(data.encode("utf-8"))
        terminal.process.stdin.flush()

    def write_approved(
        self, terminal_id: str, approvals, proposal_id: str, token: str, completion_marker: str | None = None
    ) -> str:
        action = approvals.consume(proposal_id, token, terminal_id)
        terminal = self._lookup(terminal_id)
        if Path(terminal.record.cwd).resolve() != Path(action.cwd).resolve():
            raise PermissionError("Action working directory does not match the terminal")
        marker = completion_marker or f"__JSON_CODR_ACTION_DONE__:{proposal_id}:"
        if terminal.record.shell == "powershell":
            command = (
                "$jsonCodrExit=0; try { & { " + action.command
                + " }; if (-not $?) { $jsonCodrExit=1 } } "
                + "catch { Write-Error $_; $jsonCodrExit=1 }; "
                + f'Write-Output ("{marker}" + $jsonCodrExit)'
            )
        else:
            command = f"({action.command}) & echo {marker}%ERRORLEVEL%"
        self.write(terminal_id, command + "\r\n")
        return marker

    def read(self, terminal_id: str, timeout: float = 0.1) -> str:
        terminal = self._lookup(terminal_id)
        try:
            return terminal.output.get(timeout=timeout)
        except queue.Empty:
            return ""

    def read_after(self, terminal_id: str, sequence: int, timeout: float = 0.1) -> list[tuple[int, str]]:
        terminal = self._lookup(terminal_id)
        with terminal.condition:
            terminal.condition.wait_for(
                lambda: any(item_sequence > sequence for item_sequence, _ in terminal.history)
                or terminal.record.status != "running",
                timeout=timeout,
            )
            return [item for item in terminal.history if item[0] > sequence]

    def resize(self, terminal_id: str, cols: int, rows: int) -> None:
        if not 2 <= cols <= 1000 or not 1 <= rows <= 500:
            raise ValueError("Invalid terminal dimensions")
        terminal = self._lookup(terminal_id)
        if terminal.record.backend == "conpty" and terminal.record.status == "running":
            terminal.process.setwinsize(rows, cols)

    def interrupt(self, terminal_id: str) -> None:
        terminal = self._lookup(terminal_id)
        if terminal.record.backend == "conpty":
            if terminal.record.status == "running":
                terminal.process.sendintr()
            return
        if terminal.process.poll() is None:
            terminal.process.send_signal(signal.CTRL_BREAK_EVENT)

    def close(self, terminal_id: str) -> None:
        terminal = self._lookup(terminal_id)
        if terminal.record.backend == "conpty":
            try:
                terminal.process.close(force=True)
            except OSError:
                if terminal.process.isalive():
                    completed = subprocess.run(
                        ["taskkill", "/PID", str(terminal.record.pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if completed.returncode != 0 and terminal.process.isalive():
                        raise
            self._mark_closed(terminal)
            return
        if terminal.process.poll() is None:
            terminal.process.terminate()
            try:
                terminal.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                terminal.process.kill()
                terminal.process.wait(timeout=3)
        self._mark_closed(terminal)

    def close_all(self) -> None:
        with self._lock:
            terminal_ids = list(self._terminals)
        for terminal_id in terminal_ids:
            try:
                self.close(terminal_id)
            except (OSError, RuntimeError):
                pass
        with self._lock:
            self._terminals.clear()

    def _lookup(self, terminal_id: str) -> _TerminalProcess:
        with self._lock:
            terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise KeyError(terminal_id)
        return terminal
