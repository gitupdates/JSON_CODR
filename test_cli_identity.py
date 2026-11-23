import tempfile
import unittest
from pathlib import Path

from web_app.core.auth import LocalRequestEvidence
from web_app.core.cli_identity import CliIdentityService, DpapiTokenStore
from web_app.core.identity import IdentityService


class CliIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.identity = IdentityService(root / "data", security_root=root / "security")
        self.user = self.identity.bootstrap("development", "Administrator").user
        self.identity.confirm_development_bypass(
            LocalRequestEvidence("127.0.0.1", "127.0.0.1", "127.0.0.1", {}),
            configured_host="127.0.0.1",
        )
        self.store = DpapiTokenStore(root / "profile" / "cli.dpapi")
        self.service = CliIdentityService(self.identity, self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def test_login_uses_scoped_30_day_dpapi_credential_without_plaintext(self):
        result = self.service.login("Administrator", "", machine="WORKSTATION")
        principal = self.service.status()

        self.assertIn("WORKSTATION", result.label)
        self.assertEqual(principal.credential_kind, "cli")
        self.assertIn("lesson.edit", principal.scopes)
        self.assertNotIn("identity.admin", principal.scopes)
        self.assertNotIn(self.store.load()["token"], self.store.path.read_text(encoding="ascii"))

    def test_logout_revokes_cli_without_revoking_browser_session(self):
        browser = self.identity.issue_credential(
            self.user.user_id, "browser_session", "browser", ("lesson.read",)
        )
        self.service.login("Administrator", "", machine="WORKSTATION")
        self.service.logout()

        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.identity.resolve_credential(browser.token).credential_kind, "browser_session")


if __name__ == "__main__":
    unittest.main()
