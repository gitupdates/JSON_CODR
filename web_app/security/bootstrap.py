"""One-time, expiring console claims for first-run and account enrollment."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from web_app.security.accounts import ADMINISTRATOR_ACCOUNT_ID, BASE_GROUPS, AccountService, _utc
from web_app.security.models import AccountRecord
from web_app.security.store import SecurityStore
from web_app.security.sessions import SessionPrincipal

RECENT_AUTH_WINDOW = timedelta(minutes=5)


def _hash(claim: str) -> str:
    return hashlib.sha256(claim.encode("utf-8")).hexdigest()


class BootstrapService:
    def __init__(self, store: SecurityStore, accounts: AccountService) -> None:
        self.store = store
        self.accounts = accounts

    def issue_initial_claim(self, now: datetime | None = None, lifetime: timedelta = timedelta(minutes=15)) -> str | None:
        timestamp = _utc(now)
        if lifetime <= timedelta():
            raise ValueError("claim lifetime must be positive")
        with self.store.transaction() as connection:
            if connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
                return None
            claim = secrets.token_urlsafe(32)
            connection.execute(
                "INSERT INTO bootstrap_claims (bootstrap_claim_id, claim_hash, expires_at, consumed_at, created_by_account_id, created_at, updated_at, version) "
                "VALUES (?, ?, ?, NULL, NULL, ?, ?, 1)",
                (str(uuid4()), _hash(claim), (timestamp + lifetime).isoformat(), timestamp.isoformat(), timestamp.isoformat()),
            )
            return claim

    def claim_initial_administrator(self, claim: str, username: str, password: str, now: datetime | None = None) -> AccountRecord:
        timestamp = _utc(now)
        if username != "Administrator":
            raise PermissionError("initial username must be Administrator")
        with self.store.transaction() as connection:
            row = connection.execute("SELECT bootstrap_claim_id, expires_at, consumed_at FROM bootstrap_claims WHERE claim_hash = ?", (_hash(claim),)).fetchone()
            if row is None or row[2] is not None or datetime.fromisoformat(row[1]) <= timestamp or connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
                raise PermissionError("bootstrap claim is invalid or expired")
            connection.execute("UPDATE bootstrap_claims SET consumed_at = ?, updated_at = ?, version = version + 1 WHERE bootstrap_claim_id = ?", (timestamp.isoformat(), timestamp.isoformat(), row[0]))
            return self.accounts._create_account(
                connection, username, password, set(BASE_GROUPS), timestamp, account_id=ADMINISTRATOR_ACCOUNT_ID
            )

    def _authorize_recent_admin(self, connection, principal: SessionPrincipal, now: datetime) -> None:
        row = connection.execute(
            "SELECT accounts.status, sessions.recent_auth_at, sessions.revoked_at FROM sessions JOIN accounts ON accounts.account_id = sessions.account_id "
            "JOIN memberships ON memberships.account_id = accounts.account_id JOIN groups ON groups.group_id = memberships.group_id "
            "WHERE sessions.session_id = ? AND sessions.account_id = ? AND groups.stable_id = 'admin'",
            (str(principal.session_id), str(principal.account_id)),
        ).fetchone()
        if row is None or row[0] != "active" or row[2] is not None or row[1] is None or datetime.fromisoformat(row[1]) < now - RECENT_AUTH_WINDOW:
            raise PermissionError("recent administrator authentication is required")

    def create_pending_account_with_claim(self, principal: SessionPrincipal, username: str, now: datetime | None = None) -> tuple[AccountRecord, str]:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            self._authorize_recent_admin(connection, principal, timestamp)
            account = self.accounts._create_account(connection, username, None, {"preferences", "user"}, timestamp, status="pending")
            claim = self._issue_claim_in_transaction(connection, "enrollment", account.account_id, timestamp, timedelta(minutes=15))
            return account, claim

    def issue_claim_for_principal(self, principal: SessionPrincipal, account_id: UUID, purpose: str, now: datetime | None = None, lifetime: timedelta = timedelta(minutes=15)) -> str:
        timestamp = _utc(now)
        if purpose not in {"enrollment", "reset"}:
            raise ValueError("unsupported claim purpose")
        with self.store.transaction() as connection:
            self._authorize_recent_admin(connection, principal, timestamp)
            row = connection.execute("SELECT status FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone()
            expected = "pending" if purpose == "enrollment" else "active"
            if row is None or row[0] != expected:
                raise PermissionError("claim account state is invalid")
            if purpose == "reset":
                connection.execute("UPDATE sessions SET revoked_at = ?, updated_at = ?, version = version + 1 WHERE account_id = ? AND revoked_at IS NULL", (timestamp.isoformat(), timestamp.isoformat(), str(account_id)))
            connection.execute("UPDATE auth_claims SET consumed_at = ?, updated_at = ?, version = version + 1 WHERE account_id = ? AND purpose = ? AND consumed_at IS NULL", (timestamp.isoformat(), timestamp.isoformat(), str(account_id), purpose))
            return self._issue_claim_in_transaction(connection, purpose, account_id, timestamp, lifetime)

    def issue_enrollment_claim(self, administrator_id: UUID, account_id: UUID, now: datetime | None = None, lifetime: timedelta = timedelta(minutes=15)) -> str:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            if not self.accounts.is_effective_administrator(administrator_id, connection): raise PermissionError("administrator membership is required")
            row = connection.execute("SELECT status FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone()
            if row is None or row[0] != "pending": raise PermissionError("enrollment requires pending account")
            return self._issue_claim_in_transaction(connection, "enrollment", account_id, timestamp, lifetime)

    def issue_reset_claim(self, administrator_id: UUID, account_id: UUID, now: datetime | None = None, lifetime: timedelta = timedelta(minutes=15)) -> str:
        timestamp = _utc(now)
        with self.store.transaction() as connection:
            if not self.accounts.is_effective_administrator(administrator_id, connection): raise PermissionError("administrator membership is required")
            row = connection.execute("SELECT status FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone()
            if row is None or row[0] != "active": raise PermissionError("reset requires active account")
            connection.execute("UPDATE sessions SET revoked_at = ?, updated_at = ?, version = version + 1 WHERE account_id = ? AND revoked_at IS NULL", (timestamp.isoformat(), timestamp.isoformat(), str(account_id)))
            return self._issue_claim_in_transaction(connection, "reset", account_id, timestamp, lifetime)

    def _issue_claim_in_transaction(self, connection, purpose, account_id, now, lifetime):
        if lifetime <= timedelta(): raise ValueError("claim lifetime must be positive")
        claim = secrets.token_urlsafe(32)
        connection.execute("INSERT INTO auth_claims (auth_claim_id, claim_hash, purpose, account_id, expires_at, consumed_at, created_at, updated_at, version) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 1)", (str(uuid4()), _hash(claim), purpose, str(account_id), (now + lifetime).isoformat(), now.isoformat(), now.isoformat()))
        return claim

    def _consume(self, claim: str, purpose: str, password: str, now: datetime) -> AccountRecord:
        with self.store.transaction() as connection:
            row = connection.execute("SELECT auth_claim_id, account_id, expires_at, consumed_at FROM auth_claims WHERE claim_hash = ? AND purpose = ?", (_hash(claim), purpose)).fetchone()
            if row is None or row[3] is not None or datetime.fromisoformat(row[2]) <= now:
                raise PermissionError("claim is invalid or expired")
            connection.execute("UPDATE auth_claims SET consumed_at = ?, updated_at = ?, version = version + 1 WHERE auth_claim_id = ?", (now.isoformat(), now.isoformat(), row[0]))
            account_id = UUID(row[1])
            status = connection.execute("SELECT status FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone()[0]
            if (purpose == "enrollment" and status != "pending") or (purpose == "reset" and status != "active"):
                raise PermissionError("claim account state is invalid")
            self.accounts._set_password(connection, account_id, password, now)
            if purpose == "enrollment":
                connection.execute("UPDATE accounts SET status = 'active', updated_at = ?, version = version + 1 WHERE account_id = ?", (now.isoformat(), str(account_id)))
            return self.accounts._record(connection.execute("SELECT account_id, username, username_casefold, status, created_at, updated_at, version FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone())  # type: ignore[return-value]

    def enroll_account(self, claim: str, password: str, now: datetime | None = None) -> AccountRecord:
        return self._consume(claim, "enrollment", password, _utc(now))

    def reset_account_password(self, claim: str, password: str, now: datetime | None = None) -> AccountRecord:
        return self._consume(claim, "reset", password, _utc(now))
