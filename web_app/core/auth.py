from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import ctypes
from ctypes import wintypes
import os


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
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    return key
