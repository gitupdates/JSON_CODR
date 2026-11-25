from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
import ipaddress
from pathlib import Path
import socket
from urllib.parse import urlsplit

from web_app.core.auth import CredentialKind, IssuedCredential
from web_app.core.identity import AuthenticatedPrincipal, IdentityService


def normalize_server_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("JSON_CODR server origin is invalid")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("JSON_CODR server origin is invalid") from error
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
    if not host:
        raise ValueError("JSON_CODR server origin is invalid")
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
            if not address.is_loopback or getattr(address, "ipv4_mapped", None) is not None:
                raise ValueError("JSON_CODR server origin must be loopback")
        except ValueError as error:
            raise ValueError("JSON_CODR server origin must be loopback") from error
    rendered_host = f"[{host}]" if ":" in host else host
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return f"{scheme}://{rendered_host}"
    return f"{scheme}://{rendered_host}:{port}"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data: bytes, entropy: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, source_buffer = _blob(data)
    optional, optional_buffer = _blob(entropy)
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, ctypes.byref(optional), None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)
        del source_buffer, optional_buffer


def _unprotect(data: bytes, entropy: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, source_buffer = _blob(data)
    optional, optional_buffer = _blob(entropy)
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, ctypes.byref(optional), None, None, 0, ctypes.byref(result)
    ):
        raise PermissionError("CLI credential cannot be decrypted for this Windows account")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)
        del source_buffer, optional_buffer


class DpapiTokenStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._entropy = b"JSON_CODR:credential:cli:v1"

    def save(self, credential: IssuedCredential, *, server_origin: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": 1,
            "credential_id": credential.credential_id,
            "token": credential.token,
            "expires_at": credential.expires_at.isoformat(),
        }
        if server_origin is not None:
            document["server_origin"] = normalize_server_origin(server_origin)
        encrypted = _protect(json.dumps(document).encode("utf-8"), self._entropy)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(base64.b64encode(encrypted).decode("ascii"), encoding="ascii")
        temporary.replace(self.path)

    def load(self) -> dict[str, str]:
        try:
            encrypted = base64.b64decode(self.path.read_text(encoding="ascii"), validate=True)
            document = json.loads(_unprotect(encrypted, self._entropy).decode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as error:
            raise PermissionError("CLI credential storage is unavailable or corrupt") from error
        if datetime.fromisoformat(document["expires_at"]) <= datetime.now(UTC):
            raise PermissionError("CLI credential is expired")
        return document

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class CliLoginResult:
    account: str
    label: str
    expires_at: datetime


class CliIdentityService:
    def __init__(self, identity: IdentityService, store: DpapiTokenStore):
        self.identity = identity
        self.store = store

    def login(
        self,
        username: str,
        password: str,
        machine: str | None = None,
        requested_scopes: tuple[str, ...] = (),
        server_origin: str = "http://127.0.0.1:8772",
    ) -> CliLoginResult:
        if not self.identity.authenticate_password(username, password):
            raise PermissionError("Invalid username or password")
        user = next(
            candidate for candidate in self.identity.list_users()
            if candidate.normalized_username == username.strip().casefold()
        )
        label = f"{machine or socket.gethostname()} · {datetime.now(UTC).date().isoformat()}"
        credential = self.identity.issue_credential(
            user.user_id,
            CredentialKind.cli,
            label,
            self.identity.cli_scopes(user.user_id, requested_scopes),
            lifetime=timedelta(days=30),
        )
        self.store.save(credential, server_origin=server_origin)
        return CliLoginResult(user.username, label, credential.expires_at)

    def status(self) -> AuthenticatedPrincipal:
        document = self.store.load()
        return self.identity.resolve_credential(document["token"], required_kind=CredentialKind.cli)

    def logout(self) -> None:
        document = self.store.load()
        principal = self.identity.resolve_credential(document["token"], required_kind=CredentialKind.cli)
        self.identity.revoke_credential(
            principal.credential_id,
            actor_id=principal.user_id,
            reason="CLI logout",
        )
        self.store.delete()
