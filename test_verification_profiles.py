import json
import sys
import tempfile
import unittest
from pathlib import Path

from web_app.core.verification_profiles import VerificationProfile, VerificationProfileStore


class VerificationProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = VerificationProfileStore(self.root)
        self.profile = VerificationProfile(
            profile_id="unit-tests",
            executable=sys.executable,
            argument_template=("-m", "unittest", "{target}"),
            cwd_rule="project_root",
            timeout_seconds=60,
            max_output_bytes=1048576,
            network_policy="allow",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_profile_administration_requires_its_own_scope(self):
        """Treating profile storage as unscoped runtime input must fail this test."""
        with self.assertRaisesRegex(PermissionError, "profile administration"):
            self.store.replace((self.profile,))

    def test_resolve_and_digest_detect_profile_tampering(self):
        """Skipping profile-digest verification must fail this test."""
        self.store.replace((self.profile,), scopes=("verification.profiles.manage",))
        digest = self.store.profile_digest()
        self.assertEqual(self.store.resolve("unit-tests"), self.profile)

        document = json.loads(self.store.path.read_text(encoding="utf-8"))
        document["profiles"][0]["executable"] = "cmd.exe"
        self.store.path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "digest"):
            self.store.resolve("unit-tests")
        self.assertTrue(digest.startswith("sha256:"))

    def test_profile_rejects_interpreters_and_absolute_arguments(self):
        """Allowing shell interpreters or absolute arguments must fail this test."""
        with self.assertRaisesRegex(ValueError, "interpreter"):
            VerificationProfile(
                profile_id="cmd", executable="cmd.exe", argument_template=("/c", "echo ok"),
                cwd_rule="project_root", timeout_seconds=10, max_output_bytes=4096, network_policy="allow",
            )
        with self.assertRaisesRegex(ValueError, "absolute"):
            self.store.replace((
                VerificationProfile(
                    profile_id="unsafe-template", executable=sys.executable, argument_template=("/tmp/unsafe",),
                    cwd_rule="project_root", timeout_seconds=10, max_output_bytes=4096, network_policy="allow",
                ),
            ), scopes=("verification.profiles.manage",))

    def test_profile_requires_an_exact_executable_path(self):
        """Resolving an executable through mutable PATH state must fail this test."""
        with self.assertRaisesRegex(ValueError, "exact absolute path"):
            VerificationProfile(
                profile_id="path-resolved",
                executable="python",
                argument_template=("-V",),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="allow",
            )
