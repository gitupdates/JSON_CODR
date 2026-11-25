from contextlib import closing
from datetime import UTC, datetime, timedelta
import json
import os
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path

from web_app.core.auth import load_or_create_protected_key
from web_app.core.identity import IdentityService


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)

    def now(self):
        return self.value


class CredentialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.security_root = self.root.parent / f".{self.root.name}-identity-test"
        self.addCleanup(shutil.rmtree, self.security_root, True)
        self.clock = Clock()
        self.service = IdentityService(self.root, now=self.clock.now, security_root=self.security_root)
        bootstrap = self.service.bootstrap("production", "Administrator")
        self.user = bootstrap.user
        self.password = bootstrap.temporary_credential.secret

    def test_browser_credential_is_hashed_scoped_and_resolves_to_principal(self):
        issued = self.service.issue_credential(
            self.user.user_id,
            "browser_session",
            "Edge on local machine",
            ("identity.self",),
        )

        self.assertNotIn(issued.token, repr(issued))
        self.assertNotIn(issued.token, json.dumps(issued.public_view(), default=str))
        principal = self.service.resolve_credential(issued.token, required_kind="browser_session")
        self.assertEqual(principal.user_id, self.user.user_id)
        self.assertEqual(principal.credential_kind, "browser_session")
        self.assertEqual(principal.scopes, ("identity.self",))
        self.assertEqual(issued.expires_at, self.clock.now() + timedelta(days=30))
        self.assertEqual(issued.idle_expires_at, self.clock.now() + timedelta(hours=12))
        with closing(sqlite3.connect(self.service.database_path)) as connection:
            stored = connection.execute(
                "SELECT token_hash, scopes_json FROM identity_sessions WHERE credential_id=?",
                (issued.credential_id,),
            ).fetchone()
        self.assertNotEqual(stored[0], issued.token)
        self.assertEqual(json.loads(stored[1]), ["identity.self"])

    def test_revocation_is_visible_on_the_next_resolution(self):
        issued = self.service.issue_credential(self.user.user_id, "cli", "host 2026-11-23", ("lesson.read",))
        self.assertEqual(self.service.resolve_credential(issued.token).credential_id, issued.credential_id)

        self.service.revoke_credential(issued.credential_id, actor_id=self.user.user_id, reason="test")

        with self.assertRaisesRegex(PermissionError, "revoked"):
            self.service.resolve_credential(issued.token)

    def test_kind_revocation_does_not_disturb_other_kinds(self):
        browser = self.service.issue_credential(self.user.user_id, "browser_session", "browser", ("identity.self",))
        cli = self.service.issue_credential(self.user.user_id, "cli", "cli", ("lesson.read",))

        self.service.revoke_kind(self.user.user_id, "cli", actor_id=self.user.user_id, reason="rotate cli")

        self.assertEqual(self.service.resolve_credential(browser.token).credential_kind, "browser_session")
        with self.assertRaises(PermissionError):
            self.service.resolve_credential(cli.token)

    def test_expired_idle_and_corrupt_credentials_fail_closed(self):
        browser = self.service.issue_credential(self.user.user_id, "browser_session", "browser", ("identity.self",))
        self.clock.value += timedelta(hours=12, seconds=1)

        with self.assertRaisesRegex(PermissionError, "expired"):
            self.service.resolve_credential(browser.token)
        with self.assertRaisesRegex(PermissionError, "invalid"):
            self.service.resolve_credential("not-a-real-token")

    def test_cli_defaults_to_thirty_days_and_service_scopes_stay_separate(self):
        cli = self.service.issue_credential(self.user.user_id, "cli", "host 2026-11-23", ("lesson.read", "lesson.audit"))
        verifier = self.service.issue_credential(
            self.user.user_id,
            "service",
            "lesson verifier",
            ("lesson.verify", "lesson.verification.record"),
        )

        self.assertEqual(cli.expires_at, self.clock.now() + timedelta(days=30))
        self.assertEqual(
            self.service.resolve_credential(verifier.token, required_scope="lesson.verify").scopes,
            ("lesson.verify", "lesson.verification.record"),
        )
        with self.assertRaisesRegex(PermissionError, "scope"):
            self.service.resolve_credential(verifier.token, required_scope="lesson.edit")

    def test_password_change_revokes_existing_credentials(self):
        issued = self.service.issue_credential(self.user.user_id, "browser_session", "browser", ("identity.self",))

        self.service.change_password("Administrator", self.password, "replacement-password")

        with self.assertRaises(PermissionError):
            self.service.resolve_credential(issued.token)

    def test_install_key_and_audit_anchor_are_not_stored_in_sqlite(self):
        issued = self.service.issue_credential(self.user.user_id, "cli", "cli", ("lesson.read",))
        self.service.revoke_credential(issued.credential_id, actor_id=self.user.user_id, reason="audit")

        self.assertTrue(self.service.protected_key_path.is_file())
        self.assertTrue(self.service.audit_anchor_path.is_file())
        self.assertNotIn(self.root.resolve(), self.service.protected_key_path.resolve().parents)
        self.assertNotIn(self.root.resolve(), self.service.audit_anchor_path.resolve().parents)
        database_bytes = self.service.database_path.read_bytes()
        self.assertNotIn(issued.token.encode(), database_bytes)
        self.assertNotIn(self.service._hmac_key, database_bytes)
        self.assertNotEqual(self.service.protected_key_path.read_bytes(), self.service._hmac_key)

    @unittest.skipUnless(os.name == "nt", "DPAPI is available only on Windows")
    def test_windows_protected_keys_reopen_reliably(self):
        key_root = self.root / "dpapi-round-trips"
        key_root.mkdir()

        for index in range(32):
            path = key_root / f"key-{index}.dpapi"
            created = load_or_create_protected_key(path)
            reopened = load_or_create_protected_key(path)
            self.assertEqual(reopened, created, f"protected key {index} did not round-trip")

    def test_production_transition_atomically_replaces_development_password_and_revokes_credentials(self):
        transition_root = self.root / "transition"
        transition_security = self.root / "transition-security"
        service = IdentityService(
            transition_root,
            now=self.clock.now,
            security_root=transition_security,
        )
        administrator = service.bootstrap_nonproduction_administrator(
            "Password123", "Administrator"
        ).user
        browser = service.issue_credential(
            administrator.user_id, "browser_session", "development browser", ("identity.self",)
        )
        cli = service.issue_credential(
            administrator.user_id, "cli", "development cli", ("lesson.read",)
        )
        service_token = service.issue_credential(
            administrator.user_id, "service", "development service", ("lesson.read",)
        )
        self.assertEqual(browser.expires_at, self.clock.now() + timedelta(days=36_500))
        self.assertIsNone(browser.idle_expires_at)

        replacement = service.activate_production()

        self.assertEqual(service.bootstrap_state().mode, "production")
        self.assertEqual(replacement.expires_at, self.clock.now() + timedelta(minutes=30))
        self.assertFalse(service.authenticate_password("Administrator", "Password123"))
        self.assertTrue(service.authenticate_password("Administrator", replacement.secret))
        self.assertTrue(service.get_user(administrator.user_id).require_password_change)
        for credential in (browser, cli, service_token):
            with self.subTest(kind=credential.kind):
                with self.assertRaisesRegex(PermissionError, "revoked"):
                    service.resolve_credential(credential.token)

    def test_existing_development_install_is_upgraded_to_permanent_credentials(self):
        transition_root = self.root / "existing-development"
        transition_security = self.root / "existing-development-security"
        service = IdentityService(
            transition_root,
            now=self.clock.now,
            security_root=transition_security,
        )
        service.bootstrap_nonproduction_administrator("Password123", "Administrator")
        with closing(sqlite3.connect(service.database_path)) as connection:
            with connection:
                connection.execute(
                    "UPDATE identity_bootstrap_state SET development_credentials_permanent=0 WHERE singleton=1"
                )

        upgraded = IdentityService(
            transition_root,
            now=self.clock.now,
            security_root=transition_security,
        )

        self.assertTrue(upgraded.bootstrap_state().credentials_permanent)


if __name__ == "__main__":
    unittest.main()
