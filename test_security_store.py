import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from web_app.security.models import AccountRecord
from web_app.security.passwords import PasswordHasher
from web_app.security.store import SecurityStore
from web_app.security import store as security_store


class SecurityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "security.sqlite3"
        self.store = SecurityStore(self.database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_security_store_initializes_once_and_rolls_back_failed_transaction(self) -> None:
        self.store.initialize()
        self.store.initialize()

        with self.assertRaisesRegex(RuntimeError, "abort"):
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO accounts "
                    "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), "Transient", "transient", "active", "2026-11-21T00:00:00+00:00", "2026-11-21T00:00:00+00:00", 1),
                )
                raise RuntimeError("abort transaction")

        with self.store.transaction() as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            self.assertTrue(
                {
                    "accounts", "credentials", "sessions", "groups", "memberships", "capabilities",
                    "policy_entries", "resource_acls", "policy_state", "audit_entries", "bootstrap_claims",
                    "migration_ledger",
                }.issubset(tables)
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT epoch FROM policy_state WHERE state_id = 1").fetchone()[0], 0)

    def test_account_storage_identity_is_uuid_not_username(self) -> None:
        self.store.initialize()
        account_id = uuid4()
        account = AccountRecord(
            account_id=account_id,
            username="Alice",
            username_casefold="alice",
            status="active",
            created_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
            updated_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
            version=1,
        )

        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO accounts "
                "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(account.account_id), account.username, account.username_casefold, account.status,
                    account.created_at.isoformat(), account.updated_at.isoformat(), account.version,
                ),
            )
            connection.execute(
                "UPDATE accounts SET username = ?, username_casefold = ?, version = version + 1 "
                "WHERE account_id = ?",
                ("Alicia", "alicia", str(account_id)),
            )
            stored_id = connection.execute(
                "SELECT account_id FROM accounts WHERE username_casefold = ?", ("alicia",)
            ).fetchone()[0]
            self.assertEqual(stored_id, str(account_id))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO accounts "
                    "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), "ALICIA", "alicia", "active", "2026-11-21T00:00:00+00:00", "2026-11-21T00:00:00+00:00", 1),
                )

    def test_argon2id_hash_never_contains_password_and_verifies(self) -> None:
        password = "correct horse battery staple"
        hasher = PasswordHasher()

        password_hash = hasher.hash_password(password)

        self.assertNotIn(password, password_hash)
        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertTrue(hasher.verify_password(password, password_hash))
        self.assertFalse(hasher.verify_password("incorrect", password_hash))

    def test_foreign_keys_reject_orphan_membership(self) -> None:
        self.store.initialize()

        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO memberships (membership_id, account_id, group_id, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), str(uuid4()), str(uuid4()), "2026-11-21T00:00:00+00:00", "2026-11-21T00:00:00+00:00", 1),
                )

    def test_memberships_require_explicit_utc_update_timestamp(self) -> None:
        self.store.initialize()
        account_id = str(uuid4())
        group_id = str(uuid4())
        timestamp = "2026-11-21T00:00:00+00:00"

        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO accounts "
                "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (account_id, "Member", "member", "active", timestamp, timestamp, 1),
            )
            connection.execute(
                "INSERT INTO groups "
                "(group_id, stable_id, display_name, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, "user", "User", timestamp, timestamp, 1),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO memberships (membership_id, account_id, group_id, created_at, version) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), account_id, group_id, timestamp, 1),
                )

    def test_failed_schema_initialization_leaves_no_partial_schema(self) -> None:
        original_schema = security_store._SCHEMA
        security_store._SCHEMA = f"{original_schema}\nCREATE TABLE incomplete ("
        try:
            with self.assertRaises(sqlite3.Error):
                self.store.initialize()
        finally:
            security_store._SCHEMA = original_schema

        connection = sqlite3.connect(self.database_path)
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(tables, [])

    def test_entity_ids_reject_null_noncanonical_and_non_uuid_values(self) -> None:
        self.store.initialize()
        timestamp = "2026-11-21T00:00:00+00:00"
        account_id = str(uuid4())
        capability_id = str(uuid4())

        with self.store.transaction() as connection:
            for invalid_id in (None, "not-a-uuid", str(uuid4()).upper()):
                username = f"InvalidAccount-{uuid4()}"
                with self.subTest(table="accounts", invalid_id=invalid_id), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO accounts "
                        "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (invalid_id, username, username.casefold(), "active", timestamp, timestamp, 1),
                    )
                with self.subTest(table="groups", invalid_id=invalid_id), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO groups "
                        "(group_id, stable_id, display_name, created_at, updated_at, version) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (invalid_id, f"invalid-{uuid4()}", "Invalid", timestamp, timestamp, 1),
                    )

            connection.execute(
                "INSERT INTO accounts "
                "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (account_id, "Valid", "valid", "active", timestamp, timestamp, 1),
            )
            connection.execute(
                "INSERT INTO capabilities "
                "(capability_id, stable_id, description, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (capability_id, "test.capability", "test", timestamp, timestamp, 1),
            )
            for invalid_id in (None, "not-a-uuid", str(uuid4()).upper()):
                with self.subTest(table="sessions", invalid_id=invalid_id), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO sessions "
                        "(session_id, account_id, token_hash, issued_at, idle_expires_at, absolute_expires_at, "
                        "last_seen_at, policy_epoch, created_at, updated_at, version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (invalid_id, account_id, f"hash-{uuid4()}", timestamp, timestamp, timestamp, timestamp, 0, timestamp, timestamp, 1),
                    )
                with self.subTest(table="policy_entries", invalid_id=invalid_id), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO policy_entries "
                        "(policy_entry_id, account_id, capability_id, resource_pattern, action_pattern, effect, scope, created_at, updated_at, version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (invalid_id, account_id, capability_id, "resource", "action", "grant", "own", timestamp, timestamp, 1),
                    )
                with self.subTest(table="audit_entries", invalid_id=invalid_id), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO audit_entries "
                        "(audit_entry_id, resource_id, action, decision, reason_code, entry_hash, created_at, updated_at, version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (invalid_id, "resource", "action", "deny", "test", f"hash-{uuid4()}", timestamp, timestamp, 1),
                    )

    def test_nullable_uuid_references_reject_malformed_non_null_values(self) -> None:
        self.store.initialize()
        timestamp = "2026-11-21T00:00:00+00:00"
        account_id = str(uuid4())
        capability_id = str(uuid4())

        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO accounts "
                "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (account_id, "Owner", "owner", "active", timestamp, timestamp, 1),
            )
            connection.execute(
                "INSERT INTO capabilities "
                "(capability_id, stable_id, description, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (capability_id, "test.nullable", "test", timestamp, timestamp, 1),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO policy_entries "
                    "(policy_entry_id, account_id, capability_id, resource_pattern, action_pattern, effect, scope, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), "not-a-uuid", capability_id, "resource", "action", "grant", "own", timestamp, timestamp, 1),
                )
            for column in ("actor_account_id", "session_id", "correlation_id"):
                with self.subTest(column=column), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        f"INSERT INTO audit_entries "
                        f"(audit_entry_id, {column}, resource_id, action, decision, reason_code, entry_hash, created_at, updated_at, version) "
                        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(uuid4()), "not-a-uuid", "resource", "action", "deny", "test", f"hash-{uuid4()}", timestamp, timestamp, 1),
                    )

    def test_transaction_boundary_rejects_fabricated_casefolds_and_non_utc_timestamps(self) -> None:
        self.store.initialize()
        timestamp = "2026-11-21T00:00:00+00:00"

        with self.store.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO accounts "
                    "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), "Alice", "fabricated", "active", timestamp, timestamp, 1),
                )
            connection.execute(
                "INSERT INTO accounts "
                "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid4()), "Alice", "alice", "active", timestamp, timestamp, 1),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO accounts "
                    "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), "ALICE", "alice", "active", timestamp, timestamp, 1),
                )
            for invalid_timestamp in ("not-a-timestamp", "2026-11-21T00:00:00+01:00"):
                username = f"timestamp-{uuid4()}"
                with self.subTest(invalid_timestamp=invalid_timestamp), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO accounts "
                        "(account_id, username, username_casefold, status, created_at, updated_at, version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (str(uuid4()), username, username.casefold(), "active", invalid_timestamp, timestamp, 1),
                    )

    def test_preconstraint_schema_version_fails_closed(self) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("PRAGMA user_version = 1")
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "unsupported security schema version: 1"):
            self.store.initialize()


if __name__ == "__main__":
    unittest.main()
