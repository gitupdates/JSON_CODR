import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from web_app.core.verification_profiles import VerificationProfile, VerificationProfileStore


class _Administrator:
    roles = ("administrator",)
    scopes = ("verification.profiles.manage",)
    credential_id = "credential-1"
    authentication_source = "browser_session"


def _resolve_administrator(token, *, required_scope):
    if token != "admin-token" or required_scope != "verification.profiles.manage":
        raise PermissionError("invalid administrator credential")
    return _Administrator()


class VerificationProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = VerificationProfileStore(
            self.root,
            administration_resolver=_resolve_administrator,
            integrity_key=b"profile-integrity-test-key",
        )
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
        self.store.replace((self.profile,), credential="admin-token")
        digest = self.store.profile_digest()
        self.assertEqual(self.store.resolve("unit-tests"), self.profile)

        document = json.loads(self.store.path.read_text(encoding="utf-8"))
        document["profiles"][0]["executable"] = "cmd.exe"
        self.store.path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "digest"):
            self.store.resolve("unit-tests")
        self.assertTrue(digest.startswith("hmac-sha256:"))

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
            ), credential="admin-token")

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

    def test_recomputed_unkeyed_digest_does_not_authorize_profile_tampering(self):
        """Rewriting a profile and recomputing a public digest must fail this test."""
        self.store.replace((self.profile,), credential="admin-token")
        document = json.loads(self.store.path.read_text(encoding="utf-8"))
        document["profiles"][0]["executable"] = sys.executable + ".tampered"
        canonical = json.dumps(
            {"profiles": document["profiles"]},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        document["digest"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        self.store.path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "integrity"):
            self.store.resolve("unit-tests")

    def test_profile_administration_requires_authenticated_administrator_role(self):
        """A resolver result without an Administrator role must fail this test."""
        class _NonAdministrator:
            roles = ("editor",)
            scopes = ("verification.profiles.manage",)
            credential_id = "credential-2"
            authentication_source = "browser_session"

        store = VerificationProfileStore(
            self.root / "other",
            administration_resolver=lambda token, required_scope: _NonAdministrator(),
            integrity_key=b"profile-integrity-test-key",
        )
        with self.assertRaisesRegex(PermissionError, "Administrator"):
            store.replace((self.profile,), credential="admin-token")
