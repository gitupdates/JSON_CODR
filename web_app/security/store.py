"""Versioned transactional SQLite storage for security-sensitive records."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    username_casefold TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE credentials (
    credential_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    password_changed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL,
    idle_expires_at TEXT NOT NULL,
    absolute_expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    recent_auth_at TEXT,
    revoked_at TEXT,
    policy_epoch INTEGER NOT NULL CHECK (policy_epoch >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE groups (
    group_id TEXT PRIMARY KEY,
    stable_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE memberships (
    membership_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES groups(group_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    UNIQUE (account_id, group_id)
);

CREATE TABLE capabilities (
    capability_id TEXT PRIMARY KEY,
    stable_id TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE policy_entries (
    policy_entry_id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(account_id) ON DELETE CASCADE,
    group_id TEXT REFERENCES groups(group_id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capabilities(capability_id) ON DELETE RESTRICT,
    resource_pattern TEXT NOT NULL,
    action_pattern TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('grant', 'deny')),
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    CHECK ((account_id IS NULL) != (group_id IS NULL))
);

CREATE TABLE resource_acls (
    resource_acl_id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(account_id) ON DELETE CASCADE,
    group_id TEXT REFERENCES groups(group_id) ON DELETE CASCADE,
    resource_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    permission TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    CHECK ((account_id IS NULL) != (group_id IS NULL))
);

CREATE TABLE policy_state (
    state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
    epoch INTEGER NOT NULL CHECK (epoch >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE audit_entries (
    audit_entry_id TEXT PRIMARY KEY,
    actor_account_id TEXT,
    session_id TEXT,
    correlation_id TEXT,
    resource_id TEXT NOT NULL,
    action TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    policy_digest TEXT,
    revision_digest TEXT,
    previous_entry_hash TEXT,
    entry_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE bootstrap_claims (
    bootstrap_claim_id TEXT PRIMARY KEY,
    claim_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_by_account_id TEXT REFERENCES accounts(account_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);

CREATE TABLE migration_ledger (
    migration_ledger_id TEXT PRIMARY KEY,
    migration_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    backup_digest TEXT,
    details_digest TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1)
);
"""


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
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
