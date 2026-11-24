import json
import hashlib
import hmac
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
            argument_template=("-m", "unittest", "{target:token}"),
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

    def test_active_profiles_are_immutable_when_the_disk_document_is_tampered(self):
        """Disk changes must not alter the effective in-memory profile set."""
        self.store.replace((self.profile,), credential="admin-token")
        digest = self.store.profile_digest()
        self.assertEqual(self.store.resolve("unit-tests"), self.profile)

        document = json.loads(self.store.path.read_text(encoding="utf-8"))
        document["profiles"][0]["executable"] = "cmd.exe"
        self.store.path.write_text(json.dumps(document), encoding="utf-8")

        self.assertEqual(self.store.resolve("unit-tests"), self.profile)
        self.assertEqual(self.store.profile_digest(), digest)
        self.assertTrue(digest.startswith("hmac-sha256:"))

    def test_restart_requires_authenticated_activation_against_a_trusted_digest(self):
        """Knowing the HMAC key must not make a rewritten disk profile effective after restart."""
        key = b"profile-integrity-test-key"
        trusted_digest = self.store.replace((self.profile,), credential="admin-token")
        document = json.loads(self.store.path.read_text(encoding="utf-8"))
        document["profiles"][0]["executable"] = sys.executable + ".tampered"
        canonical = json.dumps(
            {"profiles": document["profiles"]},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        attacker_digest = f"hmac-sha256:{hmac.new(key, canonical, hashlib.sha256).hexdigest()}"
        document["digest"] = attacker_digest
        self.store.path.write_text(json.dumps(document), encoding="utf-8")

        restarted = VerificationProfileStore(
            self.root,
            administration_resolver=_resolve_administrator,
            integrity_key=key,
        )
        with self.assertRaisesRegex(RuntimeError, "activation"):
            restarted.resolve("unit-tests")
        with self.assertRaisesRegex(PermissionError, "administration"):
            restarted.activate(attacker_digest)
        with self.assertRaisesRegex(ValueError, "trusted digest"):
            restarted.activate(trusted_digest, credential="admin-token")
        with self.assertRaisesRegex(RuntimeError, "activation"):
            restarted.resolve("unit-tests")

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

    def test_profile_requires_typed_placeholders(self):
        """Untyped caller substitutions must never enter executable arguments."""
        with self.assertRaisesRegex(ValueError, "typed placeholder"):
            VerificationProfile(
                profile_id="untyped", executable=sys.executable, argument_template=("{target}",),
                cwd_rule="project_root", timeout_seconds=10, max_output_bytes=4096, network_policy="allow",
            )

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

        restarted = VerificationProfileStore(
            self.root,
            administration_resolver=_resolve_administrator,
            integrity_key=b"profile-integrity-test-key",
        )
        with self.assertRaisesRegex(ValueError, "integrity"):
            restarted.activate(document["digest"], credential="admin-token")

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
