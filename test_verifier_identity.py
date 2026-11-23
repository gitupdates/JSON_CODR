import tempfile
import unittest
from pathlib import Path

from web_app.core.identity import IdentityService
from web_app.core.verifier_identity import VERIFIER_SCOPES, VERIFIER_USERNAME, VerifierIdentityService


class VerifierIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.identity = IdentityService(self.root / "data", security_root=self.root / "security")
        self.administrator = self.identity.bootstrap("production", "Administrator").user
        self.author = self.identity.create_user("author", "Author")
        self.verifier = VerifierIdentityService(self.identity, self.root / "data")

    def tearDown(self):
        self.temporary.cleanup()

    def test_service_account_is_noninteractive_and_verification_only(self):
        principal = self.verifier.ensure_service_account()

        self.assertEqual(principal.username, VERIFIER_USERNAME)
        self.assertEqual(principal.scopes, VERIFIER_SCOPES)
        self.assertFalse(self.identity.authenticate_password(VERIFIER_USERNAME, ""))
        self.assertNotIn("lesson.promote_global", principal.scopes)
        self.assertTrue(self.verifier.automatic_lesson_activation_ready())

    def test_verification_requires_three_distinct_accounts(self):
        principal = self.verifier.ensure_service_account()
        record = self.verifier.record_verification(
            "lesson-1",
            author_id=self.author.user_id,
            actor_id=self.administrator.user_id,
            outcome="passed",
            evidence={"test": "passed"},
        )
        self.assertEqual(record.verifier_id, principal.user_id)
        with self.assertRaisesRegex(PermissionError, "distinct accounts"):
            self.verifier.record_verification(
                "lesson-2",
                author_id=self.administrator.user_id,
                actor_id=self.administrator.user_id,
                outcome="passed",
                evidence={},
            )


if __name__ == "__main__":
    unittest.main()
