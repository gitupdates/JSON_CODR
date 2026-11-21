"""Server-side, hashed-token sessions for local accounts."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from web_app.security.store import SecurityStore


SESSION_COOKIE_NAME = "json_codr_session"


def _utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("security timestamps must be UTC-aware")
    return value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionPrincipal:
    account_id: UUID
    session_id: UUID
    username: str
    status: str
    recent_auth_at: datetime | None


@dataclass(frozen=True)
class IssuedSession:
    session_id: UUID
    token: str


class SessionService:
    def __init__(self, store: SecurityStore, *, secure_cookies: bool = True) -> None:
        self.store = store
        self.secure_cookies = secure_cookies

    def _insert(self, connection: sqlite3.Connection, account_id: UUID, now: datetime, idle: timedelta, absolute: timedelta) -> IssuedSession:
        active = connection.execute("SELECT status FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone()
        if active is None or active[0] != "active":
            raise PermissionError("account is not active")
        token = secrets.token_urlsafe(32)
        session_id = uuid4()
        idle_expires = now + idle
        absolute_expires = now + absolute
        connection.execute(
            "INSERT INTO sessions (session_id, account_id, token_hash, issued_at, idle_expires_at, absolute_expires_at, last_seen_at, recent_auth_at, revoked_at, policy_epoch, created_at, updated_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, 1)",
            (str(session_id), str(account_id), _hash(token), now.isoformat(), idle_expires.isoformat(), absolute_expires.isoformat(), now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
        )
        return IssuedSession(session_id, token)

    def create(self, account_id: UUID, now: datetime | None = None, *, idle_lifetime: timedelta = timedelta(minutes=30), absolute_lifetime: timedelta = timedelta(hours=8)) -> IssuedSession:
        timestamp = _utc(now)
        if idle_lifetime <= timedelta() or absolute_lifetime <= timedelta():
            raise ValueError("session lifetimes must be positive")
        with self.store.transaction() as connection:
            return self._insert(connection, account_id, timestamp, idle_lifetime, absolute_lifetime)

    def _lookup(self, connection: sqlite3.Connection, token: str, now: datetime, touch: bool = True) -> SessionPrincipal | None:
        row = connection.execute(
            "SELECT sessions.session_id, sessions.account_id, accounts.username, accounts.status, sessions.recent_auth_at, sessions.idle_expires_at, sessions.absolute_expires_at, sessions.revoked_at, sessions.last_seen_at "
            "FROM sessions JOIN accounts ON accounts.account_id = sessions.account_id WHERE sessions.token_hash = ?", (_hash(token),)
        ).fetchone()
        if row is None:
            return None
        if row[3] != "active" or row[7] is not None or datetime.fromisoformat(row[5]) <= now or datetime.fromisoformat(row[6]) <= now:
            connection.execute("UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?, version = version + 1 WHERE session_id = ?", (now.isoformat(), now.isoformat(), row[0]))
            return None
        if touch:
            idle_window = datetime.fromisoformat(row[5]) - datetime.fromisoformat(row[8])
            if idle_window <= timedelta():
                connection.execute("UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?, version = version + 1 WHERE session_id = ?", (now.isoformat(), now.isoformat(), row[0]))
                return None
            new_idle = min(now + idle_window, datetime.fromisoformat(row[6]))
            connection.execute("UPDATE sessions SET last_seen_at = ?, idle_expires_at = ?, updated_at = ?, version = version + 1 WHERE session_id = ?", (now.isoformat(), new_idle.isoformat(), now.isoformat(), row[0]))
        return SessionPrincipal(UUID(row[1]), UUID(row[0]), row[2], row[3], datetime.fromisoformat(row[4]) if row[4] else None)

    def lookup(self, token: str | None, now: datetime | None = None) -> SessionPrincipal | None:
        if not token:
            return None
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            return self._lookup(connection, token, timestamp)

    def rotate(self, token: str, now: datetime | None = None) -> IssuedSession:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            principal = self._lookup(connection, token, timestamp, touch=False)
            if principal is None:
                raise PermissionError("session is not valid")
            connection.execute("UPDATE sessions SET revoked_at = ?, updated_at = ?, version = version + 1 WHERE session_id = ?", (timestamp.isoformat(), timestamp.isoformat(), str(principal.session_id)))
            return self._insert(connection, principal.account_id, timestamp, timedelta(minutes=30), timedelta(hours=8))

    def logout(self, token: str, now: datetime | None = None) -> None:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            connection.execute("UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?, version = version + 1 WHERE token_hash = ?", (timestamp.isoformat(), timestamp.isoformat(), _hash(token)))

    def logout_all(self, account_id: UUID, now: datetime | None = None) -> None:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            connection.execute("UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?, version = version + 1 WHERE account_id = ?", (timestamp.isoformat(), timestamp.isoformat(), str(account_id)))

    def mark_reauthenticated(self, token: str, now: datetime | None = None) -> bool:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            principal = self._lookup(connection, token, timestamp, touch=False)
            if principal is None:
                return False
            connection.execute("UPDATE sessions SET recent_auth_at = ?, updated_at = ?, version = version + 1 WHERE session_id = ?", (timestamp.isoformat(), timestamp.isoformat(), str(principal.session_id)))
            return True

    def list_sessions(self, account_id: UUID, now: datetime | None = None) -> list[dict[str, str | bool | None]]:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT session_id, issued_at, last_seen_at, recent_auth_at, revoked_at, idle_expires_at, absolute_expires_at FROM sessions WHERE account_id = ? ORDER BY issued_at DESC", (str(account_id),)).fetchall()
            return [{"session_id": row[0], "issued_at": row[1], "last_seen_at": row[2], "recent_auth_at": row[3], "revoked_at": row[4], "idle_expires_at": row[5], "absolute_expires_at": row[6], "active": row[4] is None and datetime.fromisoformat(row[5]) > timestamp and datetime.fromisoformat(row[6]) > timestamp} for row in rows]

    def revoke_session(self, account_id: UUID, session_id: UUID, now: datetime | None = None) -> bool:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            result = connection.execute("UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?, version = version + 1 WHERE session_id = ? AND account_id = ?", (timestamp.isoformat(), timestamp.isoformat(), str(session_id), str(account_id)))
            return result.rowcount == 1

    @staticmethod
    def cookie_header(token: str) -> str:
        return f"{SESSION_COOKIE_NAME}={token}; HttpOnly; Path=/; SameSite=Strict"

    def set_cookie(self, response, token: str) -> None:
        response.set_cookie(SESSION_COOKIE_NAME, token, httponly=True, samesite="strict", secure=self.secure_cookies, path="/")

    def clear_cookie(self, response) -> None:
        response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="strict", secure=self.secure_cookies, path="/")
