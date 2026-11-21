import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from web_app.security.accounts import AccountService, LastAdministratorError
from web_app.security.bootstrap import BootstrapService
from web_app.security.passwords import PasswordHasher
from web_app.security.sessions import SessionService
from web_app.security.store import SecurityStore


class AccountSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = SecurityStore(Path(self.temporary_directory.name) / "security.sqlite3")
        self.passwords = PasswordHasher()
        self.accounts = AccountService(self.store, self.passwords)
        self.sessions = SessionService(self.store)
        self.bootstrap = BootstrapService(self.store, self.accounts)
        self.now = datetime(2026, 11, 21, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_bootstrap_claim_is_one_time_expiring_and_creates_administrator_in_all_groups(self) -> None:
        claim = self.bootstrap.issue_initial_claim(now=self.now, lifetime=timedelta(minutes=5))
        expired = self.bootstrap.issue_initial_claim(now=self.now, lifetime=timedelta(seconds=1))
        administrator = self.bootstrap.claim_initial_administrator(
            claim, "Administrator", "correct horse battery staple", now=self.now
        )
        self.assertEqual(administrator.username, "Administrator")
        self.assertEqual(
            self.accounts.group_stable_ids(administrator.account_id),
            {"preferences", "user", "designer", "admin", "developer"},
        )
        with self.assertRaises(PermissionError):
            self.bootstrap.claim_initial_administrator(claim, "Other", "another password", now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.claim_initial_administrator(
                expired, "Late", "another password", now=self.now + timedelta(seconds=2)
            )

    def test_login_rotates_session_and_cookie_contains_no_account_identity(self) -> None:
        account = self.accounts.create_account("Alice", "correct horse battery staple")
        first = self.sessions.create(account.account_id, now=self.now)
        second = self.sessions.rotate(first.token, now=self.now + timedelta(seconds=1))
        self.assertIsNone(self.sessions.lookup(first.token, now=self.now + timedelta(seconds=1)))
        principal = self.sessions.lookup(second.token, now=self.now + timedelta(seconds=1))
        self.assertEqual(principal.account_id, account.account_id)
        self.assertNotIn(str(account.account_id), second.token)
        self.assertNotIn(account.username, second.token)
        cookie = self.sessions.cookie_header(second.token)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn(str(account.account_id), cookie)

    def test_idle_absolute_expiry_logout_all_and_password_reset_revoke_sessions(self) -> None:
        account = self.accounts.create_account("Alice", "correct horse battery staple")
        idle = self.sessions.create(
            account.account_id, now=self.now, idle_lifetime=timedelta(seconds=1), absolute_lifetime=timedelta(minutes=5)
        )
        self.assertIsNone(self.sessions.lookup(idle.token, now=self.now + timedelta(seconds=2)))
        one = self.sessions.create(account.account_id, now=self.now)
        two = self.sessions.create(account.account_id, now=self.now)
        self.sessions.logout_all(account.account_id, now=self.now)
        self.assertIsNone(self.sessions.lookup(one.token, now=self.now))
        self.assertIsNone(self.sessions.lookup(two.token, now=self.now))
        reset = self.sessions.create(account.account_id, now=self.now)
        self.accounts.reset_password(account.account_id, "a newer correct password", now=self.now)
        self.assertIsNone(self.sessions.lookup(reset.token, now=self.now))

    def test_custom_idle_window_survives_touch_and_service_restart(self) -> None:
        account = self.accounts.create_account("Idle", "correct horse battery staple")
        issued = self.sessions.create(account.account_id, now=self.now, idle_lifetime=timedelta(seconds=10), absolute_lifetime=timedelta(minutes=1))
        self.assertIsNotNone(self.sessions.lookup(issued.token, now=self.now + timedelta(seconds=5)))
        restarted = SessionService(self.store)
        self.assertIsNotNone(restarted.lookup(issued.token, now=self.now + timedelta(seconds=14)))
        self.assertIsNone(restarted.lookup(issued.token, now=self.now + timedelta(seconds=25)))

    def test_session_listing_reports_idle_and_absolute_expiry(self) -> None:
        account = self.accounts.create_account("Listing", "correct horse battery staple")
        idle = self.sessions.create(account.account_id, now=self.now, idle_lifetime=timedelta(seconds=1), absolute_lifetime=timedelta(minutes=1))
        absolute = self.sessions.create(account.account_id, now=self.now, idle_lifetime=timedelta(minutes=1), absolute_lifetime=timedelta(seconds=1))
        rows = self.sessions.list_sessions(account.account_id, now=self.now + timedelta(seconds=2))
        by_id = {row["session_id"]: row for row in rows}
        for issued in (idle, absolute):
            self.assertFalse(by_id[str(issued.session_id)]["active"])
        self.assertEqual(by_id[str(idle.session_id)]["idle_expires_at"], (self.now + timedelta(seconds=1)).isoformat())
        self.assertEqual(by_id[str(idle.session_id)]["absolute_expires_at"], (self.now + timedelta(minutes=1)).isoformat())
        self.assertEqual(by_id[str(absolute.session_id)]["idle_expires_at"], (self.now + timedelta(minutes=1)).isoformat())
        self.assertEqual(by_id[str(absolute.session_id)]["absolute_expires_at"], (self.now + timedelta(seconds=1)).isoformat())

    def test_absolute_expiry_throttling_recent_auth_session_revocation_and_suspension(self) -> None:
        account = self.accounts.create_account("Alice", "correct horse battery staple")
        absolute = self.sessions.create(
            account.account_id, now=self.now, idle_lifetime=timedelta(hours=1), absolute_lifetime=timedelta(seconds=1)
        )
        self.assertIsNone(self.sessions.lookup(absolute.token, now=self.now + timedelta(seconds=2)))
        for _ in range(3):
            self.assertIsNone(self.accounts.authenticate("Alice", "wrong password", now=self.now))
        self.assertIsNone(self.accounts.authenticate("Alice", "correct horse battery staple", now=self.now))
        session = self.sessions.create(account.account_id, now=self.now)
        self.assertTrue(self.sessions.mark_reauthenticated(session.token, now=self.now + timedelta(seconds=1)))
        self.assertEqual(self.sessions.lookup(session.token, now=self.now + timedelta(seconds=1)).recent_auth_at, self.now + timedelta(seconds=1))
        another = self.sessions.create(account.account_id, now=self.now)
        self.assertEqual(len(self.sessions.list_sessions(account.account_id)), 3)
        self.assertTrue(self.sessions.revoke_session(account.account_id, another.session_id, now=self.now))
        self.assertIsNone(self.sessions.lookup(another.token, now=self.now))
        self.accounts.set_status(account.account_id, "suspended", now=self.now)
        self.assertIsNone(self.sessions.lookup(session.token, now=self.now))

    def test_admin_enrollment_claim_lets_user_choose_password(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple")
        pending = self.accounts.create_pending_account("New User")
        principal = self.sessions.lookup(self.sessions.create(administrator.account_id, now=self.now).token, now=self.now)
        claim = self.bootstrap.issue_claim_for_principal(principal, pending.account_id, "enrollment", now=self.now)
        enrolled = self.bootstrap.enroll_account(claim, "user chosen password", now=self.now)
        self.assertEqual(enrolled.account_id, pending.account_id)
        self.assertTrue(self.accounts.authenticate("New User", "user chosen password"))
        self.assertEqual(self.accounts.group_stable_ids(pending.account_id), {"preferences", "user"})
        with self.assertRaises(PermissionError):
            self.bootstrap.enroll_account(claim, "new password", now=self.now)
        reset = self.bootstrap.issue_claim_for_principal(principal, pending.account_id, "reset", now=self.now)
        self.bootstrap.reset_account_password(reset, "reset chosen password", now=self.now)
        self.assertTrue(self.accounts.authenticate("New User", "reset chosen password"))
        with self.assertRaises(PermissionError):
            self.bootstrap.reset_account_password(reset, "another password", now=self.now)

    def test_recent_admin_claim_authorization_rejects_every_stale_principal_state(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple", now=self.now)
        target = self.accounts.create_pending_account("Target", now=self.now)
        issued = self.sessions.create(administrator.account_id, now=self.now)
        principal = self.sessions.lookup(issued.token, now=self.now)
        self.assertIsNotNone(principal)
        self.assertTrue(self.bootstrap.issue_claim_for_principal(principal, target.account_id, "enrollment", now=self.now))

        ordinary = self.accounts.create_account("Ordinary", "correct horse battery staple", now=self.now)
        ordinary_session = self.sessions.create(ordinary.account_id, now=self.now)
        ordinary_principal = self.sessions.lookup(ordinary_session.token, now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.issue_claim_for_principal(ordinary_principal, target.account_id, "enrollment", now=self.now)

        backup = self.accounts.create_account("Backup Admin", "correct horse battery staple", now=self.now)
        self.accounts.set_group_membership(backup.account_id, "admin", True, now=self.now)
        self.accounts.set_group_membership(administrator.account_id, "admin", False, now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.issue_claim_for_principal(principal, target.account_id, "enrollment", now=self.now)

        revoked = self.sessions.create(backup.account_id, now=self.now)
        revoked_principal = self.sessions.lookup(revoked.token, now=self.now)
        self.sessions.logout(revoked.token, now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.issue_claim_for_principal(revoked_principal, target.account_id, "enrollment", now=self.now)

        idle = self.sessions.create(
            backup.account_id, now=self.now, idle_lifetime=timedelta(seconds=1), absolute_lifetime=timedelta(hours=1)
        )
        idle_principal = self.sessions.lookup(idle.token, now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.issue_claim_for_principal(
                idle_principal, target.account_id, "enrollment", now=self.now + timedelta(seconds=2)
            )

        absolute = self.sessions.create(
            backup.account_id, now=self.now, idle_lifetime=timedelta(hours=1), absolute_lifetime=timedelta(seconds=1)
        )
        absolute_principal = self.sessions.lookup(absolute.token, now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.issue_claim_for_principal(
                absolute_principal, target.account_id, "enrollment", now=self.now + timedelta(seconds=2)
            )

        stale = self.sessions.create(backup.account_id, now=self.now)
        stale_principal = self.sessions.lookup(stale.token, now=self.now)
        with self.assertRaises(PermissionError):
            self.bootstrap.issue_claim_for_principal(
                stale_principal, target.account_id, "enrollment", now=self.now + timedelta(minutes=6)
            )

    def test_claim_reissue_invalidates_prior_claim_and_reset_issuance_revokes_sessions(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple", now=self.now)
        issued = self.sessions.create(administrator.account_id, now=self.now)
        principal = self.sessions.lookup(issued.token, now=self.now)
        pending = self.accounts.create_pending_account("Claim Target", now=self.now)

        first = self.bootstrap.issue_claim_for_principal(principal, pending.account_id, "enrollment", now=self.now)
        second = self.bootstrap.issue_claim_for_principal(
            principal, pending.account_id, "enrollment", now=self.now + timedelta(seconds=1)
        )
        with self.assertRaises(PermissionError):
            self.bootstrap.enroll_account(first, "first password rejected", now=self.now + timedelta(seconds=1))
        enrolled = self.bootstrap.enroll_account(second, "chosen password", now=self.now + timedelta(seconds=1))
        target_session = self.sessions.create(enrolled.account_id, now=self.now + timedelta(seconds=2))

        reset = self.bootstrap.issue_claim_for_principal(
            principal, enrolled.account_id, "reset", now=self.now + timedelta(seconds=2)
        )
        self.assertIsNone(self.sessions.lookup(target_session.token, now=self.now + timedelta(seconds=2)))
        self.bootstrap.reset_account_password(reset, "reset password", now=self.now + timedelta(seconds=2))
        self.assertTrue(self.accounts.authenticate("Claim Target", "reset password", now=self.now + timedelta(seconds=3)))

    def test_suspended_accounts_cannot_consume_preissued_enrollment_or_reset_claims(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple", now=self.now)
        issued = self.sessions.create(administrator.account_id, now=self.now)
        principal = self.sessions.lookup(issued.token, now=self.now)

        pending = self.accounts.create_pending_account("Suspended Pending", now=self.now)
        enrollment = self.bootstrap.issue_claim_for_principal(principal, pending.account_id, "enrollment", now=self.now)
        self.accounts.set_status(pending.account_id, "suspended", now=self.now + timedelta(seconds=1))
        with self.assertRaises(PermissionError):
            self.bootstrap.enroll_account(enrollment, "must not activate", now=self.now + timedelta(seconds=1))
        self.assertEqual(self.accounts.get_account(pending.account_id).status, "suspended")

        active = self.accounts.create_account("Suspended Active", "correct horse battery staple", now=self.now)
        reset = self.bootstrap.issue_claim_for_principal(principal, active.account_id, "reset", now=self.now)
        self.accounts.set_status(active.account_id, "suspended", now=self.now + timedelta(seconds=1))
        with self.assertRaises(PermissionError):
            self.bootstrap.reset_account_password(reset, "must not reset", now=self.now + timedelta(seconds=1))
        self.assertFalse(self.accounts.authenticate("Suspended Active", "must not reset", now=self.now + timedelta(seconds=2)))

    def test_pending_account_and_memberships_roll_back_when_claim_insert_fails(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple", now=self.now)
        issued = self.sessions.create(administrator.account_id, now=self.now)
        principal = self.sessions.lookup(issued.token, now=self.now)

        with patch.object(
            self.bootstrap, "_issue_claim_in_transaction", side_effect=sqlite3.IntegrityError("injected claim failure")
        ):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "injected claim failure"):
                self.bootstrap.create_pending_account_with_claim(principal, "Rolled Back", now=self.now)

        with self.store.transaction() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM accounts WHERE username_casefold = 'rolled back'").fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM memberships JOIN accounts USING (account_id) WHERE accounts.username_casefold = 'rolled back'"
                ).fetchone()[0], 0
            )

    def test_plural_base_groups_and_memberships_merge_into_canonical_singular_ids(self) -> None:
        account = self.accounts.create_account("Legacy Member", "correct horse battery staple", now=self.now)
        legacy = {"users": "user", "designers": "designer", "administrators": "admin", "developers": "developer"}
        timestamp = self.now.isoformat()
        with self.store.transaction() as connection:
            canonical = {
                stable_id: connection.execute("SELECT group_id FROM groups WHERE stable_id = ?", (stable_id,)).fetchone()[0]
                for stable_id in legacy.values()
            }
            for plural, singular in legacy.items():
                plural_group_id = str(uuid4())
                connection.execute(
                    "INSERT INTO groups (group_id, stable_id, display_name, description, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, '', ?, ?, 1)",
                    (plural_group_id, plural, plural.title(), timestamp, timestamp),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO memberships (membership_id, account_id, group_id, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (str(uuid4()), str(account.account_id), canonical[singular], timestamp, timestamp),
                )
                connection.execute(
                    "INSERT INTO memberships (membership_id, account_id, group_id, created_at, updated_at, version) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (str(uuid4()), str(account.account_id), plural_group_id, timestamp, timestamp),
                )

        self.accounts.create_pending_account("Migration Trigger", now=self.now)

        with self.store.transaction() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM groups WHERE stable_id IN ('users', 'designers', 'administrators', 'developers')"
                ).fetchone()[0], 0
            )
            memberships = connection.execute(
                "SELECT groups.stable_id, COUNT(*) FROM memberships JOIN groups USING (group_id) "
                "WHERE memberships.account_id = ? GROUP BY groups.stable_id",
                (str(account.account_id),),
            ).fetchall()
            self.assertEqual(dict(memberships), {"admin": 1, "designer": 1, "developer": 1, "preferences": 1, "user": 1})

    def test_login_throttle_uses_normalized_account_and_client_buckets_without_raw_unknowns(self) -> None:
        whitespace = self.accounts.create_account("Whitespace", "correct horse battery staple", now=self.now)
        for username in ("Whitespace", " whitespace ", "WHITESPACE"):
            self.assertIsNone(
                self.accounts.authenticate(username, "wrong password", now=self.now, client_context="client-a")
            )
        self.assertIsNone(
            self.accounts.authenticate(whitespace.username, "correct horse battery staple", now=self.now, client_context="client-a")
        )

        renamed = self.accounts.create_account("Before Rename", "correct horse battery staple", now=self.now)
        for _ in range(2):
            self.assertIsNone(
                self.accounts.authenticate("Before Rename", "wrong password", now=self.now, client_context="rename-client")
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE accounts SET username = 'After Rename', username_casefold = 'after rename', updated_at = ?, version = version + 1 "
                "WHERE account_id = ?",
                (self.now.isoformat(), str(renamed.account_id)),
            )
        self.assertIsNone(
            self.accounts.authenticate("After Rename", "wrong password", now=self.now, client_context="rename-client")
        )
        self.assertIsNone(
            self.accounts.authenticate("After Rename", "correct horse battery staple", now=self.now, client_context="rename-client")
        )

        separated = self.accounts.create_account("Separated", "correct horse battery staple", now=self.now)
        for _ in range(3):
            self.assertIsNone(
                self.accounts.authenticate("Separated", "wrong password", now=self.now, client_context="blocked-client")
            )
        self.assertEqual(
            self.accounts.authenticate(
                "Separated", "correct horse battery staple", now=self.now, client_context="different-client"
            ).account_id,
            separated.account_id,
        )

        raw_unknown = " Secret Unknown Identifier "
        with patch.object(self.passwords, "verify_password", wraps=self.passwords.verify_password) as verify_password:
            self.assertIsNone(
                self.accounts.authenticate(raw_unknown, "wrong password", now=self.now, client_context="unknown-client")
            )
        self.assertTrue(
            any(call.args[1] == self.accounts._dummy_password_hash for call in verify_password.call_args_list),
            "unknown usernames must execute dummy Argon2 verification",
        )
        with self.store.transaction() as connection:
            persisted_keys = "\n".join(row[0] for row in connection.execute("SELECT username_casefold FROM login_throttles"))
        self.assertNotIn(raw_unknown.strip().casefold(), persisted_keys.casefold())

    def test_last_administrator_cannot_be_suspended_or_demoted(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple")
        with self.assertRaises(LastAdministratorError):
            self.accounts.set_status(administrator.account_id, "suspended")
        with self.assertRaises(LastAdministratorError):
            self.accounts.set_group_membership(administrator.account_id, "admin", False)


if __name__ == "__main__":
    unittest.main()
