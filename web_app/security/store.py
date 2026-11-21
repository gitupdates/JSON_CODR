"""Versioned transactional SQLite storage for security-sensitive records."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE accounts (
    account_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(account_id)),
    username TEXT NOT NULL,
    username_casefold TEXT NOT NULL UNIQUE CHECK (username_casefold = unicode_casefold(username)),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE credentials (
    credential_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(credential_id)),
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE CHECK (is_canonical_uuid(account_id)),
    password_hash TEXT NOT NULL,
    password_changed_at TEXT NOT NULL CHECK (is_utc_timestamp(password_changed_at)),
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE sessions (
    session_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(session_id)),
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE CHECK (is_canonical_uuid(account_id)),
    token_hash TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL CHECK (is_utc_timestamp(issued_at)),
    idle_expires_at TEXT NOT NULL CHECK (is_utc_timestamp(idle_expires_at)),
    absolute_expires_at TEXT NOT NULL CHECK (is_utc_timestamp(absolute_expires_at)),
    last_seen_at TEXT NOT NULL CHECK (is_utc_timestamp(last_seen_at)),
    recent_auth_at TEXT CHECK (recent_auth_at IS NULL OR is_utc_timestamp(recent_auth_at)),
    revoked_at TEXT CHECK (revoked_at IS NULL OR is_utc_timestamp(revoked_at)),
    policy_epoch INTEGER NOT NULL CHECK (policy_epoch >= 0),
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE groups (
    group_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(group_id)),
    stable_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE memberships (
    membership_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(membership_id)),
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE CHECK (is_canonical_uuid(account_id)),
    group_id TEXT NOT NULL REFERENCES groups(group_id) ON DELETE RESTRICT CHECK (is_canonical_uuid(group_id)),
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1),
    UNIQUE (account_id, group_id)
);

CREATE TABLE capabilities (
    capability_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(capability_id)),
    stable_id TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE policy_entries (
    policy_entry_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(policy_entry_id)),
    account_id TEXT REFERENCES accounts(account_id) ON DELETE CASCADE CHECK (account_id IS NULL OR is_canonical_uuid(account_id)),
    group_id TEXT REFERENCES groups(group_id) ON DELETE CASCADE CHECK (group_id IS NULL OR is_canonical_uuid(group_id)),
    capability_id TEXT NOT NULL REFERENCES capabilities(capability_id) ON DELETE RESTRICT CHECK (is_canonical_uuid(capability_id)),
    resource_pattern TEXT NOT NULL,
    action_pattern TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('grant', 'deny')),
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1),
    CHECK ((account_id IS NULL) != (group_id IS NULL))
);

CREATE TABLE resource_acls (
    resource_acl_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(resource_acl_id)),
    account_id TEXT REFERENCES accounts(account_id) ON DELETE CASCADE CHECK (account_id IS NULL OR is_canonical_uuid(account_id)),
    group_id TEXT REFERENCES groups(group_id) ON DELETE CASCADE CHECK (group_id IS NULL OR is_canonical_uuid(group_id)),
    resource_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    permission TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1),
    CHECK ((account_id IS NULL) != (group_id IS NULL))
);

CREATE TABLE policy_state (
    state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
    epoch INTEGER NOT NULL CHECK (epoch >= 0),
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE audit_entries (
    audit_entry_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(audit_entry_id)),
    actor_account_id TEXT CHECK (actor_account_id IS NULL OR is_canonical_uuid(actor_account_id)),
    session_id TEXT CHECK (session_id IS NULL OR is_canonical_uuid(session_id)),
    correlation_id TEXT CHECK (correlation_id IS NULL OR is_canonical_uuid(correlation_id)),
    resource_id TEXT NOT NULL,
    action TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    policy_digest TEXT,
    revision_digest TEXT,
    previous_entry_hash TEXT,
    entry_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE bootstrap_claims (
    bootstrap_claim_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(bootstrap_claim_id)),
    claim_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL CHECK (is_utc_timestamp(expires_at)),
    consumed_at TEXT CHECK (consumed_at IS NULL OR is_utc_timestamp(consumed_at)),
    created_by_account_id TEXT REFERENCES accounts(account_id) ON DELETE RESTRICT CHECK (created_by_account_id IS NULL OR is_canonical_uuid(created_by_account_id)),
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE migration_ledger (
    migration_ledger_id TEXT NOT NULL PRIMARY KEY CHECK (is_canonical_uuid(migration_ledger_id)),
    migration_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    backup_digest TEXT,
    details_digest TEXT,
    created_at TEXT NOT NULL CHECK (is_utc_timestamp(created_at)),
    updated_at TEXT NOT NULL CHECK (is_utc_timestamp(updated_at)),
    version INTEGER NOT NULL CHECK (version >= 1)
);
"""


def _is_canonical_uuid(value: object) -> int:
    if not isinstance(value, str):
        return 0
    try:
        return int(str(UUID(value)) == value)
    except ValueError:
        return 0


def _is_utc_timestamp(value: object) -> int:
    if not isinstance(value, str):
        return 0
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return 0
    return int(timestamp.tzinfo is not None and timestamp.utcoffset() == timezone.utc.utcoffset(timestamp))


def _unicode_casefold(value: object) -> str | None:
    return value.casefold() if isinstance(value, str) else None


class SecurityStore:
    """Owns a small versioned SQLite database and explicit transactions."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        """Create the schema once, or reject an incompatible schema version."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO policy_state (state_id, epoch, created_at, updated_at, version) "
                    "VALUES (1, 0, ?, ?, 1)",
                    ("1970-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00"),
                )
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif version != _SCHEMA_VERSION:
                raise RuntimeError(f"unsupported security schema version: {version}")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a connection that commits atomically or rolls back on failure."""
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.create_function("is_canonical_uuid", 1, _is_canonical_uuid, deterministic=True)
        connection.create_function("is_utc_timestamp", 1, _is_utc_timestamp, deterministic=True)
        connection.create_function("unicode_casefold", 1, _unicode_casefold, deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
