import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from web_app.core.capabilities import CapabilityRegistry
from web_app.core.contracts import (
    CapabilityManifest,
    ExecutionMode,
    RuntimeIdentity,
    TaskCommand,
)


class ProbeAdapter:
    def __init__(self, succeeds: bool) -> None:
        self.succeeds = succeeds
        self.probes: list[RuntimeIdentity] = []

    def probe(self, request: dict[str, object], context: RuntimeIdentity) -> object:
        self.probes.append(context)
        return SimpleNamespace(
            succeeded=self.succeeds,
            code="probe.ok" if self.succeeds else "probe.failed",
            safe_message="probe completed" if self.succeeds else "probe failed",
            evidence_digest="sha256:" + ("1" if self.succeeds else "0") * 64,
        )


def verify_probe(observation: object) -> bool:
    return observation.succeeded and observation.code == "probe.ok"


def manifest(
    implementation_id: str,
    *,
    modes: tuple[ExecutionMode, ...] = (ExecutionMode.native,),
    platforms: tuple[str, ...] = (),
    runtime_requirements: tuple[str, ...] = (),
    native_models: tuple[str, ...] = (),
    brokered_models: tuple[str, ...] = (),
    required_permissions: tuple[str, ...] = (),
    required_packages: tuple[str, ...] = (),
    model_scope: str = "allowlist",
) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="code.edit",
        implementation_id=implementation_id,
        version="1.0.0",
        modes=modes,
        platforms=platforms,
        runtime_requirements=runtime_requirements,
        native_models=native_models,
        brokered_models=brokered_models,
        required_permissions=required_permissions,
        required_packages=required_packages,
        model_scope=model_scope,
        authority="host_builtin",
        manifest_digest="sha256:" + "a" * 64,
    )


def context(**updates: object) -> RuntimeIdentity:
    values: dict[str, object] = {
        "platform": "windows",
        "runtime_ids": ("python-3.15",),
        "model_ids": ("native-model", "broker-model"),
        "granted_permissions": ("project.write",),
        "installed_packages": ("editor-package",),
        "runtime_fingerprint": "sha256:" + "b" * 64,
        "hardware_profile_id": "cpu",
        "hardware_fingerprint": "sha256:" + "c" * 64,
        "model_digests": {
            "native-model": "sha256:" + "d" * 64,
            "broker-model": "sha256:" + "e" * 64,
        },
    }
    values.update(updates)
    return RuntimeIdentity(**values)


class CapabilityRegistryTests(unittest.TestCase):
    def test_registration_is_deterministic(self):
        registry = CapabilityRegistry()
        registry.register(manifest("code.edit.zeta", native_models=("native-model",)), lambda: ProbeAdapter(True), verify_probe)
        registry.register(manifest("code.edit.alpha", native_models=("native-model",)), lambda: ProbeAdapter(True), verify_probe)

        self.assertEqual(
            [entry.model_dump(mode="json") for entry in registry.describe()],
            [
                {
                    "schema_version": "1",
                    "capability_id": "code.edit",
                    "implementation_id": "code.edit.alpha",
                    "version": "1.0.0",
                    "modes": ["native"],
                    "platforms": [],
                    "runtime_requirements": [],
                    "native_models": ["native-model"],
                    "brokered_models": [],
                    "required_permissions": [],
                    "required_packages": [],
                    "model_scope": "allowlist",
                    "authority": "host_builtin",
                    "manifest_digest": "sha256:" + "a" * 64,
                },
                {
                    "schema_version": "1",
                    "capability_id": "code.edit",
                    "implementation_id": "code.edit.zeta",
                    "version": "1.0.0",
                    "modes": ["native"],
                    "platforms": [],
                    "runtime_requirements": [],
                    "native_models": ["native-model"],
                    "brokered_models": [],
                    "required_permissions": [],
                    "required_packages": [],
                    "model_scope": "allowlist",
                    "authority": "host_builtin",
                    "manifest_digest": "sha256:" + "a" * 64,
                },
            ],
        )

    def test_duplicate_implementation_is_rejected(self):
        registry = CapabilityRegistry()
        implementation = manifest("code.edit.native", native_models=("native-model",))
        registry.register(implementation, lambda: ProbeAdapter(True), verify_probe)

        with self.assertRaisesRegex(ValueError, "duplicate implementation"):
            registry.register(implementation, lambda: ProbeAdapter(True), verify_probe)
        with self.assertRaisesRegex(ValueError, "unknown"):
            registry.probe({"capability_id": "code.search", "model_id": "native-model", "mode": "native"}, context())

    def test_resolution_filters_platform_runtime_and_model_but_not_policy(self):
        registry = CapabilityRegistry()
        compatible = manifest(
            "code.edit.compatible",
            platforms=("windows",),
            runtime_requirements=("python-3.15",),
            native_models=("native-model",),
            required_permissions=("project.write",),
        )
        registry.register(compatible, lambda: ProbeAdapter(True), verify_probe)
        registry.register(manifest("code.edit.other-platform", platforms=("linux",), native_models=("native-model",)), lambda: ProbeAdapter(True), verify_probe)
        registry.register(manifest("code.edit.other-runtime", runtime_requirements=("node-22",), native_models=("native-model",)), lambda: ProbeAdapter(True), verify_probe)
        registry.register(manifest("code.edit.other-model", native_models=("other-model",)), lambda: ProbeAdapter(True), verify_probe)
        registry.register(manifest("code.edit.denied", native_models=("native-model",), required_permissions=("network",)), lambda: ProbeAdapter(True), verify_probe)

        runtime = context()
        registry.probe({"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}, runtime)

        self.assertEqual(
            [result.implementation_id for result in registry.resolve({"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}, runtime)],
            ["code.edit.compatible", "code.edit.denied"],
        )

    def test_package_presence_is_not_readiness(self):
        unavailable = CapabilityRegistry()
        failed_adapter = ProbeAdapter(False)
        unavailable.register(manifest("code.edit.package", native_models=("native-model",), required_packages=("editor-package",)), lambda: failed_adapter, verify_probe)
        runtime = context()
        request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}

        self.assertEqual(unavailable.resolve(request, runtime), ())
        self.assertFalse(unavailable.probe(request, runtime)[0].runnable)
        self.assertEqual(unavailable.resolve(request, runtime), ())

        verified = CapabilityRegistry()
        successful_adapter = ProbeAdapter(True)
        verified.register(manifest("code.edit.verified", native_models=("native-model",), required_packages=("editor-package",)), lambda: successful_adapter, verify_probe)
        verified.probe(request, runtime)

        self.assertEqual([result.implementation_id for result in verified.resolve(request, runtime)], ["code.edit.verified"])
        self.assertEqual(failed_adapter.probes, [runtime])
        self.assertEqual(successful_adapter.probes, [runtime])

    def test_native_and_brokered_modes_remain_distinct(self):
        registry = CapabilityRegistry()
        registry.register(
            manifest(
                "code.edit.dual",
                modes=(ExecutionMode.native, ExecutionMode.brokered),
                native_models=("native-model",),
                brokered_models=("broker-model",),
            ),
            lambda: ProbeAdapter(True),
            verify_probe,
        )
        runtime = context()
        registry.probe({"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}, runtime)

        self.assertEqual(
            [result.implementation_id for result in registry.resolve({"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}, runtime)],
            ["code.edit.dual"],
        )
        self.assertEqual(
            [result.implementation_id for result in registry.resolve({"capability_id": "code.edit", "model_id": "native-model", "mode": "brokered"}, runtime)],
            [],
        )
        self.assertEqual(
            [result.implementation_id for result in registry.resolve({"capability_id": "code.edit", "model_id": "broker-model", "mode": "brokered"}, runtime)],
            [],
        )

        registry.probe({"capability_id": "code.edit", "model_id": "broker-model", "mode": "brokered"}, runtime)

        self.assertEqual(
            [result.implementation_id for result in registry.resolve({"capability_id": "code.edit", "model_id": "broker-model", "mode": "brokered"}, runtime)],
            ["code.edit.dual"],
        )

    def test_contracts_reject_unknown_fields_and_empty_identifiers(self):
        with self.assertRaises(ValidationError):
            TaskCommand(
                command_id="command-1",
                task_id="task-1",
                thread_id="thread-1",
                project_id="project-1",
                command_type="inspect",
                unexpected=True,
            )
        with self.assertRaises(ValidationError):
            TaskCommand(command_id="command-1", task_id="", thread_id="thread-1", project_id="project-1", command_type="inspect")
        with self.assertRaises(ValidationError):
            TaskCommand(
                schema_version="2",
                command_id="command-1",
                task_id="task-1",
                thread_id="thread-1",
                project_id="project-1",
                command_type="inspect",
            )

    def test_command_payload_is_deeply_immutable_and_serializable(self):
        command = TaskCommand(
            command_id="command-1",
            task_id="task-1",
            thread_id="thread-1",
            project_id="project-1",
            command_type="inspect",
            payload={"items": [{"name": "one"}]},
        )

        with self.assertRaises(TypeError):
            command.payload["items"][0]["name"] = "changed"
        self.assertEqual(command.model_dump(mode="json")["payload"], {"items": [{"name": "one"}]})

    def test_model_applicability_is_explicit_and_fail_closed(self):
        with self.assertRaises(ValidationError):
            manifest("code.edit.unspecified")
        with self.assertRaises(ValidationError):
            manifest("code.edit.independent-with-model", model_scope="independent", native_models=("native-model",))

        independent = manifest("code.edit.independent", model_scope="independent")
        self.assertEqual(independent.model_scope, "independent")

    def test_probe_readiness_is_specific_to_model_and_mode(self):
        registry = CapabilityRegistry()
        registry.register(
            manifest(
                "code.edit.dual-specific",
                modes=(ExecutionMode.native, ExecutionMode.brokered),
                native_models=("native-model",),
                brokered_models=("broker-model",),
            ),
            lambda: ProbeAdapter(True),
            verify_probe,
        )
        runtime = context()
        native_request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}
        brokered_request = {"capability_id": "code.edit", "model_id": "broker-model", "mode": "brokered"}

        registry.probe(native_request, runtime)

        self.assertEqual(len(registry.resolve(native_request, runtime)), 1)
        self.assertEqual(registry.resolve(brokered_request, runtime), ())

    def test_probe_readiness_is_invalidated_by_model_identity_change(self):
        registry = CapabilityRegistry()
        registry.register(
            manifest("code.edit.identity", native_models=("native-model",)),
            lambda: ProbeAdapter(True),
            verify_probe,
        )
        request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}
        original = context()
        changed = context(model_digests={"native-model": "sha256:" + "f" * 64})

        registry.probe(request, original)

        self.assertEqual(len(registry.resolve(request, original)), 1)
        self.assertEqual(registry.resolve(request, changed), ())

    def test_technical_probe_does_not_require_execution_permission(self):
        registry = CapabilityRegistry()
        registry.register(
            manifest(
                "code.edit.permissioned",
                native_models=("native-model",),
                required_permissions=("network",),
            ),
            lambda: ProbeAdapter(True),
            verify_probe,
        )
        runtime = context(granted_permissions=())
        request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}

        probe = registry.probe(request, runtime)

        self.assertTrue(probe[0].runnable)
        self.assertEqual(len(registry.resolve(request, runtime)), 1)
        self.assertEqual(probe[0].required_permissions, ("network",))

    def test_probe_reports_missing_dependency_without_calling_adapter(self):
        registry = CapabilityRegistry()
        adapter = ProbeAdapter(True)
        registry.register(
            manifest(
                "code.edit.missing-package",
                native_models=("native-model",),
                required_packages=("missing-package",),
            ),
            lambda: adapter,
            verify_probe,
        )
        request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}

        result = registry.probe(request, context())[0]

        self.assertEqual(result.status.value, "missing_dependency")
        self.assertFalse(result.runnable)
        self.assertEqual(adapter.probes, [])

    def test_result_reports_route_and_structured_probe_evidence(self):
        registry = CapabilityRegistry()
        registry.register(
            manifest("code.edit.attributed", native_models=("native-model",)),
            lambda: ProbeAdapter(True),
            verify_probe,
        )
        request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}

        result = registry.probe(request, context())[0]

        self.assertEqual(result.requested_model_id, "native-model")
        self.assertEqual(result.effective_model_id, "native-model")
        self.assertEqual(result.mode, ExecutionMode.native)
        self.assertEqual(result.evidence.code, "probe.ok")
        self.assertEqual(result.model_digest, "sha256:" + "d" * 64)
        self.assertEqual(result.runtime_fingerprint, "sha256:" + "b" * 64)
        self.assertEqual(result.hardware_profile_id, "cpu")


if __name__ == "__main__":
    unittest.main()
