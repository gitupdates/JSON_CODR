from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from web_app.core.store import TaskStore
from web_app.workspace import default_data_root


class SupervisorWatchdog:
    def __init__(
        self,
        root_dir: Path,
        store: TaskStore,
        *,
        command: tuple[str, ...],
        popen_factory: Callable = subprocess.Popen,
        max_restarts: int = 3,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.store = store
        self.command = command
        self._popen = popen_factory
        self.max_restarts = max(0, int(max_restarts))
        self.process = None
        self._exit_recorded = False
        self._restart_count = 0

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        environment = os.environ.copy()
        environment["OLLAMA_NO_CLOUD"] = "1"
        options = {"cwd": str(self.root_dir), "env": environment}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        self.process = self._popen(self.command, **options)
        self._exit_recorded = False
        self.store.record_heartbeat("web", int(self.process.pid), "starting")
        self.store.record_telemetry("runtime.child_started", {"pid": int(self.process.pid)})

    def poll_once(self) -> bool:
        if self.process is None:
            raise RuntimeError("supervisor has not started")
        exit_code = self.process.poll()
        if exit_code is not None:
            if not self._exit_recorded:
                self.store.record_heartbeat("web", int(self.process.pid), "exited")
                self.store.record_telemetry(
                    "runtime.child_exited",
                    {"pid": int(self.process.pid), "exit_code": int(exit_code)},
                )
                self._exit_recorded = True
            return False
        self.store.record_heartbeat("web", int(self.process.pid), "ready")
        return True

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.store.record_telemetry("runtime.supervisor_stopped", {})

    def recover_once(self) -> bool:
        if self.process is None or self.process.poll() is None:
            return False
        if self._restart_count >= self.max_restarts:
            self.store.record_telemetry(
                "runtime.recovery_exhausted",
                {"restart_count": self._restart_count, "exit_code": int(self.process.returncode or 0)},
            )
            return False
        previous_pid = int(self.process.pid)
        self._restart_count += 1
        self.store.record_telemetry(
            "runtime.child_restarting",
            {"previous_pid": previous_pid, "restart_count": self._restart_count},
        )
        self.process = None
        self.start()
        return True

    def run(self, interval_seconds: float = 5.0) -> int:
        self.start()
        try:
            while True:
                while self.poll_once():
                    time.sleep(interval_seconds)
                exit_code = int(self.process.returncode or 0)
                if exit_code == 0 or not self.recover_once():
                    return exit_code
        finally:
            self.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, default=default_data_root() / "core" / "tasks.sqlite")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    store = TaskStore(args.database)
    watchdog = SupervisorWatchdog(
        root,
        store,
        command=(
            sys.executable,
            "-m",
            "uvicorn",
            "web_app.app:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ),
    )
    try:
        return watchdog.run()
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
