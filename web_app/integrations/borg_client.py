from __future__ import annotations

import json
from collections.abc import Callable
from urllib import error, parse, request


class BorgClientError(RuntimeError):
    pass


class BorgClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        opener: Callable[..., object] = request.urlopen,
    ) -> None:
        normalized = base_url.rstrip("/")
        parsed = parse.urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("JSON_CODR base URL must be an HTTP or HTTPS origin")
        self.base_url = normalized
        self.timeout_seconds = timeout_seconds
        self._open = opener

    def health(self) -> dict:
        result = self._request("GET", "/api/health")
        if not isinstance(result, dict):
            raise BorgClientError("JSON_CODR health response is not an object")
        return result

    def models(self) -> list[dict]:
        result = self._request("GET", "/api/models")
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise BorgClientError("JSON_CODR model response is not a list")
        return result

    def run_workspace_task(
        self,
        *,
        session_id: str,
        project_root: str,
        prompt: str,
        model_selection: str = "auto",
        context_references: list[str] | None = None,
    ) -> dict:
        result = self._request("POST", "/api/workspace/tasks", {
            "session_id": session_id,
            "project_root": project_root,
            "prompt": prompt,
            "engine_id": "borg",
            "model_selection": model_selection,
            "context_references": context_references or [],
        })
        if not isinstance(result, dict):
            raise BorgClientError("JSON_CODR workspace response is not an object")
        return result

    def _request(self, method: str, path: str, payload: dict | None = None):
        encoded = None if payload is None else json.dumps(payload).encode("utf-8")
        outgoing = request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self._open(outgoing, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = self._error_detail(exc)
            raise BorgClientError(f"JSON_CODR API returned {exc.code}: {detail}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise BorgClientError("JSON_CODR service is unavailable") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BorgClientError("JSON_CODR returned invalid JSON") from exc

    @staticmethod
    def _error_detail(exc: error.HTTPError) -> str:
        try:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("detail", "request failed") if isinstance(payload, dict) else "request failed"
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = "request failed"
        finally:
            exc.close()
        return str(detail)[:500]
