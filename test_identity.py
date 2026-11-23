import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from web_app.designer.access import DESIGN_ACTIONS
from web_app.app import create_app
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []

    async def generate_deterministic(self, model, messages, temperature=0.0):
        return ""


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


if __name__ == "__main__":
    unittest.main()
