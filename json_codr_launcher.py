"""Stable stdlib-only launcher for selecting and owning a JSON_CODR build process."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def load_pointer(path: Path, *, fallback_root: str, fallback_revision: str, fallback_version: str) -> dict:
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "root": fallback_root,
            "revision": fallback_revision,
            "version": fallback_version,
            "previous_revision": None,
        }
    root = Path(str(payload.get("root", ""))).resolve(strict=True)
    revision = str(payload.get("revision", ""))
    version = str(payload.get("version", ""))
    if not root.is_dir() or not revision or not version:
        raise ValueError("active build pointer is incomplete")
    return {**payload, "root": str(root), "revision": revision, "version": version}


def command_for(pointer: dict, *, python: str, host: str, port: int) -> list[str]:
    return [python, "-m", "uvicorn", "web_app.app:app", "--host", host, "--port", str(port)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer", required=True)
    parser.add_argument("--fallback-root", required=True)
    parser.add_argument("--fallback-revision", required=True)
    parser.add_argument("--fallback-version", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-root")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args(argv)
    pointer = load_pointer(
        Path(arguments.pointer),
        fallback_root=arguments.fallback_root,
        fallback_revision=arguments.fallback_revision,
        fallback_version=arguments.fallback_version,
    )
    command = command_for(pointer, python=arguments.python, host=arguments.host, port=arguments.port)
    data_root = arguments.data_root or str(Path(arguments.pointer).resolve().parent / "active-data")
    if arguments.validate_only:
        print(json.dumps({"pointer": pointer, "command": command, "data_root": data_root}))
        return 0
    environment = {
        **os.environ,
        "JSON_CODR_REVISION": pointer["revision"],
        "JSON_CODR_EXPECTED_VERSION": pointer["version"],
        "JSON_CODR_DATA_ROOT": data_root,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    child = subprocess.Popen(command, cwd=pointer["root"], env=environment)
    try:
        return int(child.wait())
    except KeyboardInterrupt:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
