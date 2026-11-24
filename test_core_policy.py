import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import ExecutionMode


class CapabilityRegistryTests(unittest.TestCase):
    # Removing the registry's compatibility-operation check would let callers
    # relabel a privileged adapter as a read and bypass policy.
    def test_privileged_capabilities_reject_read_operation_spoofing(self):
        from web_app.core.capability_registry import CapabilityRegistry

        registry = CapabilityRegistry.default()
        for capability_id in (
            "native.shell",
            "native.write",
            "native.edit",
            "git.execute",
            "system.activate",
            "system.rollback",
        ):
            call = CapabilityCall(
                capability_id=capability_id,
                operation="read",
                project_root="C:/project",
            )
            with self.subTest(capability_id=capability_id):
                with self.assertRaisesRegex(ValueError, "operation"):
                    registry.normalize(call)

    def test_registry_returns_canonical_definitions(self):
        from web_app.core.capability_registry import CapabilityRegistry

        registry = CapabilityRegistry.default()

        self.assertEqual(registry.resolve("native.shell").operation, "command")
        self.assertEqual(registry.resolve("native.write").operation, "bounded_edit")
        self.assertEqual(registry.resolve("native.edit").operation, "bounded_edit")
        self.assertEqual(registry.resolve("git.execute").operation, "git")
        self.assertEqual(registry.resolve("system.activate").operation, "activation")
        self.assertEqual(registry.resolve("system.rollback").operation, "rollback")
        self.assertEqual(registry.resolve("project.patch").operation, "replace")
        self.assertEqual(registry.resolve("test.run").operation, "test")
        with self.assertRaisesRegex(LookupError, "unknown capability"):
            registry.resolve("untrusted.execute")

    def test_sensitive_capability_definitions_cannot_be_autonomous(self):
        from web_app.core.capability_registry import CapabilityDefinition

        with self.assertRaisesRegex(ValueError, "sensitive"):
            CapabilityDefinition(
                capability_id="unsafe.definition", operation="write", risk="sensitive", autonomous=True,
            )


class PersistentGrantTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, arguments=None):
        return CapabilityCall(
            capability_id="native.write",
            operation="bounded_edit",
            project_root=str(self.root),
            target_path="file.txt",
            arguments=arguments or {"content": "one"},
        )

    def test_grant_requires_matching_arguments_and_has_an_expiry(self):
        from web_app.core.policy import PolicyEffect, PolicyService

        policy = PolicyService(self.root / "policy.sqlite")
        try:
            granted = self.call()
            expires_at = datetime.now(UTC) + timedelta(minutes=5)
            policy.grant("user", "project", granted, scope="project", expires_at=expires_at)

            self.assertEqual(policy.evaluate("user", "project", granted).effect, PolicyEffect.allow)
            self.assertEqual(
                policy.evaluate("user", "project", self.call({"content": "two"})).effect,
                PolicyEffect.require_approval,
            )
            self.assertEqual(
                policy.evaluate("user", "project", granted, now=expires_at + timedelta(seconds=1)).effect,
                PolicyEffect.require_approval,
            )
        finally:
            policy.close()

    def test_grant_binds_every_effectful_execution_context(self):
        from web_app.core.policy import PolicyEffect, PolicyService

        policy = PolicyService(self.root / "policy.sqlite")
        try:
            granted = self.call()
            policy.grant("user", "project", granted, scope="project")
            changed_calls = (
                granted.model_copy(update={"project_root": str(self.root / "other")}),
                granted.model_copy(update={"mode": ExecutionMode.brokered}),
                granted.model_copy(update={"privacy_boundary": "cloud", "approved_privacy_boundary": "cloud"}),
                granted.model_copy(update={"cost_boundary": "metered", "approved_cost_boundary": "metered"}),
                granted.model_copy(update={"credential_refs": ("credential:other",)}),
            )

            for changed in changed_calls:
                with self.subTest(changed=changed.model_dump(mode="json")):
                    self.assertEqual(
                        policy.evaluate("user", "project", changed).effect,
                        PolicyEffect.require_approval,
                    )
        finally:
            policy.close()

    def test_schedule_grant_ignores_caller_supplied_schedule_id(self):
        from web_app.core.policy import PolicyEffect, PolicyService

        policy = PolicyService(self.root / "policy.sqlite")
        try:
            call = self.call().model_copy(update={"schedule_id": "nightly"})
            policy.grant("user", "project", call, scope="schedule", schedule_id="nightly")

            self.assertEqual(
                policy.evaluate("user", "project", call).effect,
                PolicyEffect.require_approval,
            )
            self.assertEqual(
                policy.evaluate("user", "project", call, trusted_schedule_id="nightly").effect,
                PolicyEffect.allow,
            )
        finally:
            policy.close()

    def test_legacy_unconstrained_grant_is_disabled_during_migration(self):
        database = self.root / "policy.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                """CREATE TABLE policy_grants (
                    principal TEXT NOT NULL, project_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL, operation TEXT NOT NULL,
                    scope TEXT NOT NULL, scope_key TEXT NOT NULL,
                    PRIMARY KEY(principal, project_id, capability_id, operation, scope, scope_key)
                )"""
            )
            connection.execute(
                "INSERT INTO policy_grants VALUES (?, ?, ?, ?, ?, ?)",
                ("user", "project", "native.write", "bounded_edit", "project", "*"),
            )
            connection.commit()
        finally:
            connection.close()

        from web_app.core.policy import PolicyEffect, PolicyService

        policy = PolicyService(database)
        try:
            self.assertEqual(policy.evaluate("user", "project", self.call()).effect, PolicyEffect.require_approval)
            legacy_count = policy._connection.execute("SELECT COUNT(*) FROM policy_legacy_grants").fetchone()[0]
            self.assertEqual(legacy_count, 1)
        finally:
            policy.close()

    def test_legacy_grant_migration_is_idempotent_when_legacy_table_exists(self):
        database = self.root / "policy.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                """CREATE TABLE policy_grants (
                    principal TEXT NOT NULL, project_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL, operation TEXT NOT NULL,
                    scope TEXT NOT NULL, scope_key TEXT NOT NULL,
                    PRIMARY KEY(principal, project_id, capability_id, operation, scope, scope_key)
                )"""
            )
            connection.execute(
                "INSERT INTO policy_grants VALUES (?, ?, ?, ?, ?, ?)",
                ("user", "project", "native.write", "bounded_edit", "project", "*"),
            )
            connection.execute(
                """CREATE TABLE policy_legacy_grants (
                    principal TEXT NOT NULL, project_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL, operation TEXT NOT NULL,
                    scope TEXT NOT NULL, scope_key TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT INTO policy_legacy_grants VALUES (?, ?, ?, ?, ?, ?)",
                ("older", "project", "native.write", "bounded_edit", "project", "*"),
            )
            connection.commit()
        finally:
            connection.close()

        from web_app.core.policy import PolicyService

        first = PolicyService(database)
        first.close()
        second = PolicyService(database)
        try:
            self.assertEqual(
                second._connection.execute("SELECT COUNT(*) FROM policy_legacy_grants").fetchone()[0],
                2,
            )
        finally:
            second.close()


if __name__ == "__main__":
    unittest.main()
