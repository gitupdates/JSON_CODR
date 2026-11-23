from __future__ import annotations

from collections.abc import Callable
import secrets
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from web_app.core.identity import AuthenticatedPrincipal, IdentityService


CookieNames = Callable[[Request], tuple[str, str, bool]]


class MutationAuthorizer:
    def __init__(self, identity: IdentityService, cookie_names: CookieNames) -> None:
        self._identity = identity
        self._cookie_names = cookie_names

    def principal(self, request: Request, scope: str) -> AuthenticatedPrincipal:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if authorization:
            if not separator or scheme.casefold() != "bearer" or not token.strip():
                raise HTTPException(status_code=401, detail="Authentication required")
            return self._resolve_bearer(token.strip(), scope)

        session_name, _, _ = self._cookie_names(request)
        token = request.cookies.get(session_name)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self._resolve(token, "browser_session", scope)

    def csrf(self, request: Request) -> None:
        if request.headers.get("authorization"):
            return
        _, csrf_name, _ = self._cookie_names(request)
        cookie = request.cookies.get(csrf_name, "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    def websocket_csrf(self, request: Request) -> str | None:
        if request.headers.get("authorization"):
            return None
        _, csrf_name, _ = self._cookie_names(request)
        cookie = request.cookies.get(csrf_name, "")
        protocol = next(
            (
                candidate.strip()
                for candidate in request.headers.get("sec-websocket-protocol", "").split(",")
                if candidate.strip().startswith("json-codr-csrf.")
            ),
            "",
        )
        token = protocol.removeprefix("json-codr-csrf.")
        if not cookie or not token or not secrets.compare_digest(cookie, token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        return protocol

    def _resolve_bearer(self, token: str, scope: str) -> AuthenticatedPrincipal:
        try:
            credential = self._identity.resolve_credential(token)
        except PermissionError as error:
            raise HTTPException(status_code=401, detail="Authentication required") from error
        if credential.credential_kind not in {"service", "cli"}:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self._resolve(token, credential.credential_kind, scope)

    def _resolve(self, token: str, kind: str, scope: str) -> AuthenticatedPrincipal:
        try:
            return self._identity.resolve_credential(
                token,
                required_kind=kind,
                required_scope=scope,
            )
        except PermissionError as error:
            try:
                self._identity.resolve_credential(token, required_kind=kind)
            except PermissionError as identity_error:
                raise HTTPException(status_code=401, detail="Authentication required") from identity_error
            raise HTTPException(status_code=403, detail="Credential scope is not allowed") from error
