import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from web_app.designer.access import DESIGN_ACTIONS
from web_app.app import create_app
from web_app.workspace import WorkspaceService
from web_app.core.auth import DevelopmentBypassSettings, LocalRequestEvidence
from web_app.core.identity import AuthenticatedPrincipal


class FakeService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []

    async def generate_deterministic(self, model, messages, temperature=0.0):
        return ""


class MutableClock:
    def __init__(self):
        self.value = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)

    def now(self):
        return self.value


class IdentityServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def service(self):
        from web_app.core.identity import IdentityService

        return IdentityService(self.root)

    def test_production_bootstrap_seeds_roles_and_one_administrator(self):
        service = self.service()
        result = service.bootstrap("production", "Administrator")

        self.assertTrue(result.created)
        self.assertEqual(result.temporary_credential.expires_in_seconds, 1800)
        self.assertTrue(result.temporary_credential.single_use)
        self.assertNotIn(result.temporary_credential.secret, repr(result))
        users = service.list_users()
        self.assertEqual([user.username for user in users], ["Administrator"])
        self.assertEqual(users[0].normalized_username, "administrator")
        self.assertEqual(users[0].roles, ("administrator",))
        roles = {role.name: set(role.grants) for role in service.list_roles()}
        self.assertEqual(set(roles), {"owner", "administrator", "designer", "editor", "contributor", "reviewer", "viewer"})
        self.assertEqual(roles["owner"], set(DESIGN_ACTIONS))
        self.assertEqual(roles["administrator"], set(DESIGN_ACTIONS))
        self.assertNotIn("design.publish", roles["designer"])

    def test_bootstrap_is_idempotent_and_username_is_case_insensitively_unique(self):
        service = self.service()
        first = service.bootstrap("production", "Administrator")
        second = service.bootstrap("production", "Administrator")

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertIsNone(second.temporary_credential)
        with self.assertRaisesRegex(ValueError, "already exists"):
            service.create_user("administrator", "Another administrator")

    def test_password_hash_uses_required_argon2id_parameters_and_authentication(self):
        service = self.service()
        result = service.bootstrap("production", "Administrator")
        secret = result.temporary_credential.secret

        self.assertTrue(service.authenticate_password("Administrator", secret))
        self.assertFalse(service.authenticate_password("missing-user", secret))
        with closing(sqlite3.connect(service.database_path)) as connection:
            stored = connection.execute("SELECT password_hash FROM identity_users").fetchone()[0]
        self.assertTrue(stored.startswith("$argon2id$v=19$m=65536,t=3,p=1$"))
        self.assertNotIn(secret, stored)

        service.change_password("Administrator", secret, "a-new-local-password")
        self.assertFalse(service.authenticate_password("Administrator", secret))
        self.assertTrue(service.authenticate_password("Administrator", "a-new-local-password"))

    def test_last_recovery_capable_account_cannot_be_disabled_or_demoted(self):
        service = self.service()
        result = service.bootstrap("production", "Administrator")
        administrator = service.list_users()[0]
        service.change_password("Administrator", result.temporary_credential.secret, "local-password")

        with self.assertRaisesRegex(PermissionError, "recovery-capable"):
            service.disable_user(administrator.user_id)
        with self.assertRaisesRegex(PermissionError, "recovery-capable"):
            service.assign_roles(administrator.user_id, ("viewer",))

    def test_user_ids_are_immutable_and_unique(self):
        service = self.service()
        service.bootstrap("production", "Administrator")
        first = service.create_user("DesignerOne", "Designer One")
        second = service.create_user("DesignerTwo", "Designer Two")

        self.assertNotEqual(first.user_id, second.user_id)
        with closing(sqlite3.connect(service.database_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE identity_users SET user_id = ? WHERE user_id = ?",
                    (second.user_id, first.user_id),
                )

    def test_app_exposes_one_identity_service_for_the_workspace(self):
        workspace = WorkspaceService(self.root)
        app = create_app(FakeService(), workspace=workspace)

        self.assertEqual(app.state.identity.database_path, self.root / "core" / "identity.sqlite")

    def test_development_bypass_requires_atomic_settings(self):
        with self.assertRaises(ValueError):
            DevelopmentBypassSettings(enabled=False, do_not_expire=True)

    def test_migrated_install_keeps_blank_login_off_until_direct_local_confirmation(self):
        from web_app.core.identity import IdentityService

        clock = MutableClock()
        service = IdentityService(self.root, now=clock.now)
        service.bootstrap_migrated("Administrator")
        evidence = LocalRequestEvidence(
            peer_host="127.0.0.1",
            host="127.0.0.1:8765",
            server_host="127.0.0.1",
            headers={},
        )

        self.assertFalse(service.development_bypass().enabled)
        status = service.confirm_development_bypass(evidence, configured_host="127.0.0.1:8765")
        self.assertTrue(status.enabled)
        self.assertEqual(status.expires_at, clock.now() + timedelta(days=30))
        self.assertTrue(service.authenticate_password("Administrator", ""))

        cli = service.issue_credential(service.list_users()[0].user_id, "cli", "cli", ("lesson.read",))
        non_expiring = service.renew_development_bypass(
            evidence, configured_host="127.0.0.1:8765", do_not_expire=True
        )
        self.assertIsNone(non_expiring.expires_at)
        self.assertEqual(cli.expires_at, clock.now() + timedelta(days=30))

    def test_blank_login_rejects_forwarding_relay_host_rebinding_and_non_loopback(self):
        from web_app.core.identity import IdentityService

        service = IdentityService(self.root)
        service.bootstrap_migrated("Administrator")
        invalid = (
            LocalRequestEvidence("192.168.1.10", "127.0.0.1:8765", "127.0.0.1", {}),
            LocalRequestEvidence("127.0.0.1", "evil.example", "127.0.0.1", {}),
            LocalRequestEvidence("127.0.0.1", "127.0.0.1:8765", "0.0.0.0", {}),
            LocalRequestEvidence("127.0.0.1", "127.0.0.1:8765", "127.0.0.1", {"x-forwarded-for": "127.0.0.1"}),
            LocalRequestEvidence("127.0.0.1", "127.0.0.1:8765", "127.0.0.1", {"via": "proxy"}),
            LocalRequestEvidence("127.0.0.1", "127.0.0.1:8765", "127.0.0.1", {}, connection_mode="ide_webview"),
        )

        for evidence in invalid:
            with self.subTest(evidence=evidence):
                with self.assertRaises(PermissionError):
                    service.confirm_development_bypass(evidence, configured_host="127.0.0.1:8765")

    def test_expired_bypass_disables_blank_login_and_opens_local_recovery(self):
        from web_app.core.identity import IdentityService

        clock = MutableClock()
        service = IdentityService(self.root, now=clock.now)
        service.bootstrap_migrated("Administrator")
        evidence = LocalRequestEvidence("::1", "localhost:8765", "::1", {})
        service.confirm_development_bypass(evidence, configured_host="localhost:8765")
        clock.value += timedelta(days=31)

        self.assertFalse(service.development_bypass().enabled)
        self.assertFalse(service.authenticate_password("Administrator", ""))
        recovery = service.begin_local_recovery(evidence, configured_host="localhost:8765")
        self.assertEqual(recovery.expires_in_seconds, 1800)
        self.assertTrue(service.authenticate_password("Administrator", recovery.secret))

    def test_design_context_is_derived_from_persisted_roles_and_profile_denies(self):
        service = self.service()
        bootstrap = service.bootstrap("production", "Administrator")
        principal = AuthenticatedPrincipal(
            user_id=bootstrap.user.user_id,
            username="Administrator",
            roles=("viewer",),
        )
        service.create_profile("no-publish", "No publishing", (), ("design.publish",))
        service.assign_profile(bootstrap.user.user_id, "no-publish", "project:demo")

        context = service.design_policy_context(principal, "project:demo")

        self.assertEqual(context.role, "administrator")
        self.assertEqual(context.profiles[0].profile_id, "no-publish")
        self.assertEqual(context.assignments[0].resource, "project:demo")

    def test_lesson_scope_matrix_and_two_account_rule_use_account_ids(self):
        service = self.service()
        bootstrap = service.bootstrap("production", "Administrator")
        viewer = service.create_user("viewer", "Viewer")

        self.assertIn("lesson.promote_global", service.lesson_scopes(bootstrap.user.user_id))
        self.assertEqual(service.lesson_scopes(viewer.user_id), ("lesson.read",))
        with self.assertRaisesRegex(PermissionError, "distinct accounts"):
            service.require_distinct_accounts(bootstrap.user.user_id, bootstrap.user.user_id)
        service.require_distinct_accounts(bootstrap.user.user_id, viewer.user_id)


if __name__ == "__main__":
    unittest.main()
