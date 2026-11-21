import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
        claim = self.bootstrap.issue_enrollment_claim(administrator.account_id, pending.account_id, now=self.now)
        enrolled = self.bootstrap.enroll_account(claim, "user chosen password", now=self.now)
        self.assertEqual(enrolled.account_id, pending.account_id)
        self.assertTrue(self.accounts.authenticate("New User", "user chosen password"))
        self.assertEqual(self.accounts.group_stable_ids(pending.account_id), {"preferences", "user"})
        with self.assertRaises(PermissionError):
            self.bootstrap.enroll_account(claim, "new password", now=self.now)
        reset = self.bootstrap.issue_reset_claim(administrator.account_id, pending.account_id, now=self.now)
        self.bootstrap.reset_account_password(reset, "reset chosen password", now=self.now)
        self.assertTrue(self.accounts.authenticate("New User", "reset chosen password"))
        with self.assertRaises(PermissionError):
            self.bootstrap.reset_account_password(reset, "another password", now=self.now)

    def test_last_administrator_cannot_be_suspended_or_demoted(self) -> None:
        administrator = self.accounts.create_initial_administrator("Administrator", "correct horse battery staple")
        with self.assertRaises(LastAdministratorError):
            self.accounts.set_status(administrator.account_id, "suspended")
        with self.assertRaises(LastAdministratorError):
            self.accounts.set_group_membership(administrator.account_id, "admin", False)


if __name__ == "__main__":
    unittest.main()
