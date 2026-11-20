from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class CanonicalRunApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, payload: dict | None = None) -> str:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read().decode("utf-8")

    def create(self, payload: dict) -> dict:
        return json.loads(self._request("/api/model-runs", payload))

    def get(self, run_id: str) -> dict:
        return json.loads(self._request(f"/api/model-runs/{urllib.parse.quote(run_id)}"))

    def export(self, run_id: str, format_name: str) -> str:
        query = urllib.parse.urlencode({"format": format_name})
        return self._request(f"/api/model-runs/{urllib.parse.quote(run_id)}/export?{query}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run the JSON_CODR all-model Code Jury")
    result.add_argument("--session", required=True, help="Existing JSON_CODR session ID")
    source = result.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="File to review")
    source.add_argument("--code", help="Inline code to review")
    result.add_argument("--url", default="http://127.0.0.1:8772")
    result.add_argument("--format", choices=("json", "markdown", "csv"), default="json")
    return result


def execute(argv=None, *, api=None, stdin=None, stdout=None) -> int:
    args = parser().parse_args(argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    prompt = args.file.read_text(encoding="utf-8") if args.file else (args.code if args.code is not None else stdin.read())
    if not prompt.strip():
        raise SystemExit("No review content was supplied")
    api = api or CanonicalRunApi(args.url)
    run = api.create({
        "session_id": args.session,
        "prompt": prompt,
        "profile": "code_jury",
        "request_key": uuid.uuid4().hex,
    })
    while run["status"] not in {"completed", "partial", "failed", "cancelled"}:
        time.sleep(0.5)
        run = api.get(run["run_id"])
    stdout.write(api.export(run["run_id"], args.format))
    if hasattr(stdout, "write"):
        stdout.write("\n")
    return 0 if run["status"] in {"completed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(execute())
