"""Transactional local-account operations with UUID-only storage joins."""

from __future__ import annotations

import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from web_app.security.models import AccountRecord
from web_app.security.passwords import PasswordHasher
from web_app.security.store import SecurityStore


BASE_GROUPS = {
    "preferences": "Preferences",
    "user": "Users",
    "designer": "Designers",
    "admin": "Administrators",
    "developer": "Developers",
}
ADMINISTRATOR_ACCOUNT_ID = uuid5(NAMESPACE_URL, "json-codr.local/administrator")


class LastAdministratorError(PermissionError):
    """Raised when a change would leave no active administrator."""


def _utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("security timestamps must be UTC-aware")
    return value


def _stamp(value: datetime) -> str:
    return value.isoformat()


class AccountService:
    def __init__(self, store: SecurityStore, passwords: PasswordHasher) -> None:
        self.store = store
        self.passwords = passwords
        self._dummy_password_hash = passwords.hash_password("json-codr-unknown-login-dummy")

    def _record(self, row: sqlite3.Row | tuple | None) -> AccountRecord | None:
        if row is None:
            return None
        return AccountRecord(
            account_id=UUID(row[0]), username=row[1], username_casefold=row[2], status=row[3],
            created_at=datetime.fromisoformat(row[4]), updated_at=datetime.fromisoformat(row[5]), version=row[6],
        )

    def get_account(self, account_id: UUID) -> AccountRecord | None:
        with self.store.transaction() as connection:
            return self._record(connection.execute(
                "SELECT account_id, username, username_casefold, status, created_at, updated_at, version "
                "FROM accounts WHERE account_id = ?", (str(account_id),)
            ).fetchone())

    def _ensure_groups(self, connection: sqlite3.Connection, now: datetime) -> dict[str, str]:
        groups: dict[str, str] = {}
        legacy = {"users": "user", "designers": "designer", "administrators": "admin", "developers": "developer"}
        for old, new in legacy.items():
            legacy_row = connection.execute("SELECT group_id FROM groups WHERE stable_id = ?", (old,)).fetchone()
            if legacy_row is None:
                continue
            canonical_row = connection.execute("SELECT group_id FROM groups WHERE stable_id = ?", (new,)).fetchone()
            if canonical_row is None:
                connection.execute(
                    "UPDATE groups SET stable_id = ?, updated_at = ?, version = version + 1 WHERE group_id = ?",
                    (new, _stamp(now), legacy_row[0]),
                )
                continue

            legacy_group_id = legacy_row[0]
            canonical_group_id = canonical_row[0]
            connection.execute(
                "DELETE FROM memberships WHERE group_id = ? AND EXISTS ("
                "SELECT 1 FROM memberships canonical WHERE canonical.account_id = memberships.account_id "
                "AND canonical.group_id = ?)",
                (legacy_group_id, canonical_group_id),
            )
            connection.execute(
                "UPDATE memberships SET group_id = ?, updated_at = ?, version = version + 1 WHERE group_id = ?",
                (canonical_group_id, _stamp(now), legacy_group_id),
            )
            for table in ("policy_entries", "resource_acls"):
                connection.execute(
                    f"UPDATE {table} SET group_id = ?, updated_at = ?, version = version + 1 WHERE group_id = ?",
                    (canonical_group_id, _stamp(now), legacy_group_id),
                )
            connection.execute("DELETE FROM groups WHERE group_id = ?", (legacy_group_id,))
        for stable_id, display_name in BASE_GROUPS.items():
            row = connection.execute("SELECT group_id FROM groups WHERE stable_id = ?", (stable_id,)).fetchone()
            if row is None:
                group_id = str(uuid4())
                connection.execute(
                    "INSERT INTO groups (group_id, stable_id, display_name, description, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, '', ?, ?, 1)",
                    (group_id, stable_id, display_name, _stamp(now), _stamp(now)),
                )
                groups[stable_id] = group_id
            else:
                groups[stable_id] = row[0]
        return groups

    def _create_account(
        self, connection: sqlite3.Connection, username: str, password: str | None, group_ids: set[str],
        now: datetime, *, account_id: UUID | None = None, status: str = "active",
    ) -> AccountRecord:
        normalized = username.strip()
        if not normalized:
            raise ValueError("username must not be empty")
        account_id = account_id or uuid4()
        timestamp = _stamp(now)
        connection.execute(
            "INSERT INTO accounts (account_id, username, username_casefold, status, created_at, updated_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (str(account_id), normalized, normalized.casefold(), status, timestamp, timestamp),
        )
        if password is not None:
            connection.execute(
                "INSERT INTO credentials (credential_id, account_id, password_hash, password_changed_at, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (str(uuid4()), str(account_id), self.passwords.hash_password(password), timestamp, timestamp, timestamp),
            )
        groups = self._ensure_groups(connection, now)
        for stable_id in group_ids:
            connection.execute(
                "INSERT INTO memberships (membership_id, account_id, group_id, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (str(uuid4()), str(account_id), groups[stable_id], timestamp, timestamp),
            )
        return self._record(connection.execute(
            "SELECT account_id, username, username_casefold, status, created_at, updated_at, version "
            "FROM accounts WHERE account_id = ?", (str(account_id),)
        ).fetchone())  # type: ignore[return-value]

    def create_account(self, username: str, password: str, now: datetime | None = None) -> AccountRecord:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            return self._create_account(connection, username, password, {"preferences", "user"}, timestamp)

    def create_pending_account(self, username: str, now: datetime | None = None) -> AccountRecord:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            return self._create_account(connection, username, None, {"preferences", "user"}, timestamp, status="pending")

    def create_initial_administrator(self, username: str, password: str, now: datetime | None = None) -> AccountRecord:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            if connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
                raise PermissionError("initial administrator has already been claimed")
            return self._create_account(
                connection, username, password, set(BASE_GROUPS), timestamp, account_id=ADMINISTRATOR_ACCOUNT_ID
            )

    def group_stable_ids(self, account_id: UUID) -> set[str]:
        with self.store.transaction() as connection:
            return {row[0] for row in connection.execute(
                "SELECT groups.stable_id FROM memberships JOIN groups ON groups.group_id = memberships.group_id "
                "WHERE memberships.account_id = ?", (str(account_id),)
            )}

    def is_effective_administrator(self, account_id: UUID, connection: sqlite3.Connection | None = None) -> bool:
        def check(active_connection: sqlite3.Connection) -> bool:
            return active_connection.execute(
                "SELECT 1 FROM accounts JOIN memberships USING (account_id) JOIN groups USING (group_id) "
                "WHERE accounts.account_id = ? AND accounts.status = 'active' AND groups.stable_id = 'admin'",
                (str(account_id),),
            ).fetchone() is not None
        if connection is not None:
            return check(connection)
        with self.store.transaction() as opened:
            return check(opened)

    def _require_not_last_administrator(self, connection: sqlite3.Connection, account_id: UUID) -> None:
        if not self.is_effective_administrator(account_id, connection):
            return
        count = connection.execute(
            "SELECT COUNT(*) FROM accounts JOIN memberships USING (account_id) JOIN groups USING (group_id) "
            "WHERE accounts.status = 'active' AND groups.stable_id = 'admin'"
        ).fetchone()[0]
        if count <= 1:
            raise LastAdministratorError("the last active administrator cannot be changed")

    def set_status(self, account_id: UUID, status: str, now: datetime | None = None) -> None:
        if status not in {"active", "suspended", "pending"}:
            raise ValueError("invalid account status")
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            if status != "active":
                self._require_not_last_administrator(connection, account_id)
            cursor = connection.execute(
                "UPDATE accounts SET status = ?, updated_at = ?, version = version + 1 WHERE account_id = ?",
                (status, _stamp(timestamp), str(account_id)),
            )
            if cursor.rowcount != 1:
                raise KeyError(account_id)
            if status != "active":
                connection.execute(
                    "UPDATE sessions SET revoked_at = ?, updated_at = ?, version = version + 1 "
                    "WHERE account_id = ? AND revoked_at IS NULL", (_stamp(timestamp), _stamp(timestamp), str(account_id))
                )
                connection.execute("UPDATE auth_claims SET consumed_at = ?, updated_at = ?, version = version + 1 WHERE account_id = ? AND consumed_at IS NULL", (_stamp(timestamp), _stamp(timestamp), str(account_id)))

    def set_group_membership(self, account_id: UUID, stable_id: str, included: bool, now: datetime | None = None) -> None:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            groups = self._ensure_groups(connection, timestamp)
            if stable_id not in groups:
                raise ValueError("unknown group")
            if stable_id == "admin" and not included:
                self._require_not_last_administrator(connection, account_id)
            if included:
                connection.execute(
                    "INSERT OR IGNORE INTO memberships (membership_id, account_id, group_id, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (str(uuid4()), str(account_id), groups[stable_id], _stamp(timestamp), _stamp(timestamp)),
                )
            else:
                connection.execute("DELETE FROM memberships WHERE account_id = ? AND group_id = ?", (str(account_id), groups[stable_id]))

    def _throttle_key(self, account_id: str | None, normalized_username: str, client_context: str) -> str:
        material = f"account:{account_id}:{client_context}" if account_id else f"unknown:{normalized_username}:{client_context}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _record_failed_login(self, connection: sqlite3.Connection, key: str, now: datetime) -> None:
        row = connection.execute("SELECT failed_count FROM login_throttles WHERE username_casefold = ?", (key,)).fetchone()
        failures = (row[0] if row else 0) + 1
        blocked_until = _stamp(now + timedelta(seconds=min(300, 2 ** min(failures, 8)))) if failures >= 3 else None
        connection.execute(
            "INSERT INTO login_throttles (username_casefold, failed_count, blocked_until, updated_at, version) VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(username_casefold) DO UPDATE SET failed_count = excluded.failed_count, blocked_until = excluded.blocked_until, updated_at = excluded.updated_at, version = login_throttles.version + 1",
            (key, failures, blocked_until, _stamp(now)),
        )

    def authenticate(self, username: str, password: str, now: datetime | None = None, *, client_context: str = "loopback") -> AccountRecord | None:
        timestamp = _utc(now)
        key = username.strip().casefold()
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT accounts.account_id, accounts.username, accounts.username_casefold, accounts.status, accounts.created_at, accounts.updated_at, accounts.version, credentials.password_hash "
                "FROM accounts LEFT JOIN credentials ON credentials.account_id = accounts.account_id WHERE accounts.username_casefold = ?", (key,)
            ).fetchone()
            bucket = self._throttle_key(row[0] if row else None, key, client_context)
            throttle = connection.execute("SELECT blocked_until FROM login_throttles WHERE username_casefold = ?", (bucket,)).fetchone()
            if throttle and throttle[0] and datetime.fromisoformat(throttle[0]) > timestamp:
                return None
            valid = self.passwords.verify_password(password, row[7]) if row and row[7] else self.passwords.verify_password(password, self._dummy_password_hash)
            if row is None or row[3] != "active" or row[7] is None or not valid:
                self._record_failed_login(connection, bucket, timestamp)
                return None
            connection.execute("DELETE FROM login_throttles WHERE username_casefold = ?", (bucket,))
            return self._record(row[:7])

    def verify_account_password(self, account_id: UUID, password: str) -> bool:
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT accounts.status, credentials.password_hash FROM accounts JOIN credentials USING (account_id) WHERE account_id = ?",
                (str(account_id),),
            ).fetchone()
            return bool(row and row[0] == "active" and self.passwords.verify_password(password, row[1]))

    def _set_password(self, connection: sqlite3.Connection, account_id: UUID, password: str, now: datetime) -> None:
        password_hash = self.passwords.hash_password(password)
        timestamp = _stamp(now)
        result = connection.execute(
            "UPDATE credentials SET password_hash = ?, password_changed_at = ?, updated_at = ?, version = version + 1 WHERE account_id = ?",
            (password_hash, timestamp, timestamp, str(account_id)),
        )
        if result.rowcount == 0:
            connection.execute(
                "INSERT INTO credentials (credential_id, account_id, password_hash, password_changed_at, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)", (str(uuid4()), str(account_id), password_hash, timestamp, timestamp, timestamp)
            )
        connection.execute(
            "UPDATE sessions SET revoked_at = ?, updated_at = ?, version = version + 1 WHERE account_id = ? AND revoked_at IS NULL",
            (timestamp, timestamp, str(account_id)),
        )

    def reset_password(self, account_id: UUID, password: str, now: datetime | None = None) -> None:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            self._set_password(connection, account_id, password, timestamp)
