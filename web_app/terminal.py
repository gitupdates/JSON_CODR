import queue
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TerminalRecord:
    id: str
    pid: int
    shell: str
    cwd: str
    status: str = "running"


@dataclass
class _TerminalProcess:
    record: TerminalRecord
    process: subprocess.Popen
    output: queue.Queue[str]


class TerminalService:
    def __init__(self) -> None:
        self._terminals: dict[str, _TerminalProcess] = {}
        self._lock = threading.Lock()

    def create(self, shell: str, cwd: Path, cols: int = 100, rows: int = 30) -> TerminalRecord:
        if shell not in {"powershell", "cmd"}:
            raise ValueError("Unsupported shell")
        working_directory = Path(cwd).resolve()
        if not working_directory.is_dir():
            raise ValueError("Working directory does not exist")
        command = (
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NoExit", "-Command", "-"]
            if shell == "powershell"
            else ["cmd.exe", "/Q"]
        )
        process = subprocess.Popen(
            command,
            cwd=working_directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        record = TerminalRecord(
            id=uuid.uuid4().hex,
            pid=process.pid,
            shell=shell,
            cwd=str(working_directory),
        )
        terminal = _TerminalProcess(record=record, process=process, output=queue.Queue(maxsize=2048))
        with self._lock:
            self._terminals[record.id] = terminal
        threading.Thread(target=self._read_output, args=(terminal,), daemon=True).start()
        return record

    @staticmethod
    def _read_output(terminal: _TerminalProcess) -> None:
        assert terminal.process.stdout is not None
        while True:
            chunk = terminal.process.stdout.read1(256)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            try:
                terminal.output.put_nowait(text)
            except queue.Full:
                try:
                    terminal.output.get_nowait()
                except queue.Empty:
                    pass
                terminal.output.put_nowait("\n[output truncated]\n" + text)
        terminal.record.status = "closed"

    def get(self, terminal_id: str) -> TerminalRecord:
        return self._lookup(terminal_id).record

    def list(self) -> list[TerminalRecord]:
        with self._lock:
            return [terminal.record for terminal in self._terminals.values()]

    def write(self, terminal_id: str, data: str) -> None:
        terminal = self._lookup(terminal_id)
        if terminal.record.status != "running" or terminal.process.stdin is None:
            raise RuntimeError("Terminal is closed")
        terminal.process.stdin.write(data.encode("utf-8"))
        terminal.process.stdin.flush()

    def read(self, terminal_id: str, timeout: float = 0.1) -> str:
        terminal = self._lookup(terminal_id)
        try:
            return terminal.output.get(timeout=timeout)
        except queue.Empty:
            return ""

    def interrupt(self, terminal_id: str) -> None:
        terminal = self._lookup(terminal_id)
        if terminal.process.poll() is None:
            terminal.process.send_signal(signal.CTRL_BREAK_EVENT)

    def close(self, terminal_id: str) -> None:
        terminal = self._lookup(terminal_id)
        if terminal.process.poll() is None:
            terminal.process.terminate()
            try:
                terminal.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                terminal.process.kill()
                terminal.process.wait(timeout=3)
        terminal.record.status = "closed"

    def _lookup(self, terminal_id: str) -> _TerminalProcess:
        with self._lock:
            terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise KeyError(terminal_id)
        return terminal
