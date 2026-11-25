from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import ipaddress
from collections.abc import Callable
from fastapi import HTTPException, Request


class CredentialKind(StrEnum):
    browser_session = "browser_session"
    cli = "cli"
    service = "service"


class CredentialScope(StrEnum):
    identity_self = "identity.self"
    identity_admin = "identity.admin"
    lesson_read = "lesson.read"
    lesson_audit = "lesson.audit"
    lesson_edit = "lesson.edit"
    lesson_disable = "lesson.disable"
    lesson_supersede = "lesson.supersede"
    lesson_remove = "lesson.remove"
    lesson_verify = "lesson.verify"
    lesson_verification_record = "lesson.verification.record"
    lesson_promote_global = "lesson.promote_global"
    verification_profiles_manage = "verification.profiles.manage"


@dataclass(frozen=True)
class DevelopmentBypassSettings:
    enabled: bool = False
    do_not_expire: bool = False
    expires_at: datetime | None = None

    def __post_init__(self):
        if self.do_not_expire and not self.enabled:
            raise ValueError("do_not_expire requires enabled development bypass")
        if self.enabled and not self.do_not_expire and self.expires_at is None:
            raise ValueError("expiring development bypass requires expires_at")
        if self.do_not_expire and self.expires_at is not None:
            raise ValueError("non-expiring development bypass cannot have expires_at")


@dataclass(frozen=True)
class LocalRequestEvidence:
    peer_host: str
    host: str
    server_host: str
    headers: dict[str, str]
    connection_mode: str = "local"

    def require_direct_loopback(self, configured_host: str) -> None:
        try:
            peer_loopback = ipaddress.ip_address(self.peer_host).is_loopback
            server_loopback = ipaddress.ip_address(self.server_host).is_loopback
        except ValueError as error:
            raise PermissionError("local identity recovery requires numeric loopback addresses") from error
        if not peer_loopback or not server_loopback:
            raise PermissionError("local identity recovery requires a direct loopback connection")
        if self.host.casefold() != configured_host.casefold():
            raise PermissionError("local identity recovery rejected the Host header")
        if self.connection_mode != "local":
            raise PermissionError("local identity recovery is unavailable through relays or IDE webviews")
        forbidden = {
            "forwarded", "via", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
            "x-real-ip", "x-t3-relay", "x-json-codr-relay", "x-envoy-external-address",
        }
        if forbidden & {name.casefold() for name in self.headers}:
            raise PermissionError("forwarded or relayed requests cannot use local identity recovery")


@dataclass(frozen=True)
class IssuedCredential:
    credential_id: str
    user_id: str
    kind: CredentialKind
    label: str
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    idle_expires_at: datetime | None
    token: str = field(repr=False)

    def public_view(self) -> dict[str, object]:
        return {
            "credential_id": self.credential_id,
            "user_id": self.user_id,
            "kind": self.kind.value,
            "label": self.label,
            "scopes": self.scopes,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "idle_expires_at": self.idle_expires_at.isoformat() if self.idle_expires_at else None,
        }


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt_protect(data: bytes) -> bytes:
    source, source_buffer = _blob(data)
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)
        del source_buffer


def _crypt_unprotect(data: bytes) -> bytes:
    source, source_buffer = _blob(data)
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)
        del source_buffer


def load_or_create_protected_key(path: Path, size: int = 32) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        payload = path.read_bytes()
        return _crypt_unprotect(payload) if os.name == "nt" else payload
    key = os.urandom(size)
    payload = _crypt_protect(key) if os.name == "nt" else key
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    return key


def require_identity_scope(identity: Callable[[], object], scope: str):
    async def dependency(request: Request):
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="authenticated credential required")
        try:
            return identity().resolve_credential(token.strip(), required_scope=scope)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    return dependency
