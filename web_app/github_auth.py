from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Callable
from uuid import uuid4


class GitHubAuthSessionNotFound(KeyError):
    pass


class GitHubAuthSessionConflict(RuntimeError):
    pass


class GitHubAuthSessionService:
    _ACTIVE_STATES = {"starting", "waiting"}
    _TOKEN_PATTERN = re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{20,}\b")
    _DEVICE_PATTERN = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")

    def __init__(
        self,
        executable_finder: Callable[[str], str | None] = shutil.which,
        process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        status_probe: Callable[[], dict[str, object]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 300,
        retention_seconds: float = 60,
        poll_interval: float = 0.1,
    ) -> None:
        self._executable_finder = executable_finder
        self._process_factory = process_factory
        self._status_probe = status_probe or (lambda: {"authenticated": True})
        self._clock = clock
        self._timeout = timeout
        self._retention_seconds = retention_seconds
        self._poll_interval = poll_interval
        self._sessions: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def start(self) -> dict[str, object]:
        with self._lock:
            self._cleanup_locked()
            if any(session["state"] in self._ACTIVE_STATES for session in self._sessions.values()):
                raise GitHubAuthSessionConflict("A GitHub login is already active")
            executable = self._executable_finder("gh")
            if not executable:
                raise RuntimeError("GitHub CLI is not installed")
            arguments = [
                executable,
                "auth",
                "login",
                "--web",
                "--hostname",
                "github.com",
                "--git-protocol",
                "https",
            ]
            try:
                process = self._process_factory(
                    arguments,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    shell=False,
                )
            except OSError as error:
                raise RuntimeError("Unable to start GitHub CLI") from error
            session_id = str(uuid4())
            session: dict[str, object] = {
                "session_id": session_id,
                "state": "starting",
                "detail": "Starting GitHub browser login...",
                "started_at": self._clock(),
                "finished_at": None,
                "device_code": None,
                "process": process,
                "cancel_requested": False,
            }
            self._sessions[session_id] = session
            threading.Thread(target=self._run_session, args=(session_id,), daemon=True).start()
            return self._public(session)

    def status(self, session_id: str) -> dict[str, object]:
        with self._lock:
            self._cleanup_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise GitHubAuthSessionNotFound(session_id)
            return self._public(session)

    def cancel(self, session_id: str) -> dict[str, object]:
        with self._lock:
            self._cleanup_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise GitHubAuthSessionNotFound(session_id)
            if session["state"] in self._ACTIVE_STATES:
                session["cancel_requested"] = True
                self._finish_locked(session, "cancelled", "GitHub login was cancelled.")
                process = session["process"]
            else:
                process = None
            result = self._public(session)
        if process is not None:
            self._terminate(process)
        return result

    def close(self) -> None:
        with self._lock:
            active = [
                (session_id, session)
                for session_id, session in self._sessions.items()
                if session["state"] in self._ACTIVE_STATES
            ]
        for session_id, _ in active:
            try:
                self.cancel(session_id)
            except GitHubAuthSessionNotFound:
                pass

    def _run_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            process = session["process"]
            started_at = float(session["started_at"])

        stdin = getattr(process, "stdin", None)
        if stdin is not None:
            try:
                stdin.write("\n")
                stdin.flush()
            except (BrokenPipeError, OSError):
                pass

        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            stream = getattr(process, "stdout", None)
            if stream is not None:
                try:
                    for line in stream:
                        output_queue.put(line)
                except (OSError, ValueError):
                    pass
            output_queue.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        output_closed = False
        while True:
            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    output_closed = True
                    break
                match = self._DEVICE_PATTERN.search(line)
                if match:
                    with self._lock:
                        current = self._sessions.get(session_id)
                        if current is not None and current["state"] in self._ACTIVE_STATES:
                            current["device_code"] = match.group(1)
                            current["state"] = "waiting"
                            current["detail"] = "Complete sign-in in your browser or at the verification URL."

            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current["cancel_requested"]:
                    return
            returncode = process.poll()
            if returncode is not None and output_closed:
                break
            if self._clock() - started_at >= self._timeout:
                self._terminate(process)
                with self._lock:
                    current = self._sessions.get(session_id)
                    if current is not None and current["state"] in self._ACTIVE_STATES:
                        self._finish_locked(current, "expired", "GitHub login timed out. Try again.")
                return
            time.sleep(self._poll_interval)

        with self._lock:
            current = self._sessions.get(session_id)
            if current is None or current["state"] not in self._ACTIVE_STATES:
                return
        if process.returncode == 0:
            try:
                account = self._status_probe()
            except Exception:
                account = {}
            if account.get("authenticated") is True:
                with self._lock:
                    current = self._sessions.get(session_id)
                    if current is not None:
                        current["login"] = account.get("login")
                        self._finish_locked(current, "authenticated", "GitHub authentication succeeded.")
                return
        with self._lock:
            current = self._sessions.get(session_id)
            if current is not None:
                self._finish_locked(current, "failed", "GitHub authentication failed or was denied.")

    def _cleanup_locked(self) -> None:
        now = self._clock()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session["finished_at"] is not None
            and now - float(session["finished_at"]) >= self._retention_seconds
        ]
        for session_id in expired:
            del self._sessions[session_id]

    def _finish_locked(self, session: dict[str, object], state: str, detail: str) -> None:
        session["state"] = state
        session["detail"] = self._TOKEN_PATTERN.sub("[redacted]", detail)[:500]
        session["finished_at"] = self._clock()

    @staticmethod
    def _terminate(process: object) -> None:
        if getattr(process, "poll")() is not None:
            return
        try:
            getattr(process, "terminate")()
            getattr(process, "wait")(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                getattr(process, "kill")()
            except OSError:
                pass

    @staticmethod
    def _public(session: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            "session_id": session["session_id"],
            "state": session["state"],
            "detail": session["detail"],
        }
        if session.get("device_code") and session["state"] == "waiting":
            result["device_code"] = session["device_code"]
            result["verification_url"] = "https://github.com/login/device"
        if session.get("login") and session["state"] == "authenticated":
            result["login"] = session["login"]
        return result
