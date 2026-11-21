"""One-time, expiring console claims for first-run and account enrollment."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from web_app.security.accounts import ADMINISTRATOR_ACCOUNT_ID, BASE_GROUPS, AccountService, _utc
from web_app.security.models import AccountRecord
from web_app.security.store import SecurityStore


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
        with self.store.transaction() as connection:
            row = connection.execute("SELECT bootstrap_claim_id, expires_at, consumed_at FROM bootstrap_claims WHERE claim_hash = ?", (_hash(claim),)).fetchone()
            if row is None or row[2] is not None or datetime.fromisoformat(row[1]) <= timestamp or connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
                raise PermissionError("bootstrap claim is invalid or expired")
            connection.execute("UPDATE bootstrap_claims SET consumed_at = ?, updated_at = ?, version = version + 1 WHERE bootstrap_claim_id = ?", (timestamp.isoformat(), timestamp.isoformat(), row[0]))
            return self.accounts._create_account(
                connection, username, password, set(BASE_GROUPS), timestamp, account_id=ADMINISTRATOR_ACCOUNT_ID
            )

    def _issue_claim(self, purpose: str, account_id: UUID, now: datetime, lifetime: timedelta) -> str:
        if lifetime <= timedelta():
            raise ValueError("claim lifetime must be positive")
        claim = secrets.token_urlsafe(32)
        with self.store.transaction() as connection:
            connection.execute("INSERT INTO auth_claims (auth_claim_id, claim_hash, purpose, account_id, expires_at, consumed_at, created_at, updated_at, version) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 1)", (str(uuid4()), _hash(claim), purpose, str(account_id), (now + lifetime).isoformat(), now.isoformat(), now.isoformat()))
        return claim

    def issue_enrollment_claim(self, administrator_id: UUID, account_id: UUID, now: datetime | None = None, lifetime: timedelta = timedelta(minutes=15)) -> str:
        timestamp = _utc(now)
        if not self.accounts.is_effective_administrator(administrator_id):
            raise PermissionError("administrator membership is required")
        return self._issue_claim("enrollment", account_id, timestamp, lifetime)

    def issue_reset_claim(self, administrator_id: UUID, account_id: UUID, now: datetime | None = None, lifetime: timedelta = timedelta(minutes=15)) -> str:
        timestamp = _utc(now)
        if not self.accounts.is_effective_administrator(administrator_id):
            raise PermissionError("administrator membership is required")
        return self._issue_claim("reset", account_id, timestamp, lifetime)

    def _consume(self, claim: str, purpose: str, password: str, now: datetime) -> AccountRecord:
        with self.store.transaction() as connection:
            row = connection.execute("SELECT auth_claim_id, account_id, expires_at, consumed_at FROM auth_claims WHERE claim_hash = ? AND purpose = ?", (_hash(claim), purpose)).fetchone()
            if row is None or row[3] is not None or datetime.fromisoformat(row[2]) <= now:
                raise PermissionError("claim is invalid or expired")
            connection.execute("UPDATE auth_claims SET consumed_at = ?, updated_at = ?, version = version + 1 WHERE auth_claim_id = ?", (now.isoformat(), now.isoformat(), row[0]))
            account_id = UUID(row[1])
            self.accounts._set_password(connection, account_id, password, now)
            return self.accounts._record(connection.execute("SELECT account_id, username, username_casefold, status, created_at, updated_at, version FROM accounts WHERE account_id = ?", (str(account_id),)).fetchone())  # type: ignore[return-value]

    def enroll_account(self, claim: str, password: str, now: datetime | None = None) -> AccountRecord:
        return self._consume(claim, "enrollment", password, _utc(now))

    def reset_account_password(self, claim: str, password: str, now: datetime | None = None) -> AccountRecord:
        return self._consume(claim, "reset", password, _utc(now))
