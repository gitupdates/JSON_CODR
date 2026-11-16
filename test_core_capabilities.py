import unittest

from web_app.core.capabilities import CapabilityRegistry
from web_app.core.contracts import CapabilityManifest, ExecutionMode, RuntimeIdentity


class ProbeAdapter:
    def __init__(self, succeeds: bool) -> None:
        self.succeeds = succeeds
        self.probes: list[RuntimeIdentity] = []

    def probe(self, context: RuntimeIdentity) -> bool:
        self.probes.append(context)
        return self.succeeds


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
    )


def context(**updates: object) -> RuntimeIdentity:
    values: dict[str, object] = {
        "platform": "windows",
        "runtime_ids": ("python-3.15",),
        "model_ids": ("native-model", "broker-model"),
        "granted_permissions": ("project.write",),
        "installed_packages": ("editor-package",),
    }
    values.update(updates)
    return RuntimeIdentity(**values)


class CapabilityRegistryTests(unittest.TestCase):
    def test_registration_is_deterministic(self):
        registry = CapabilityRegistry()
        registry.register(manifest("code.edit.zeta"), lambda: ProbeAdapter(True))
        registry.register(manifest("code.edit.alpha"), lambda: ProbeAdapter(True))

        self.assertEqual(
            [entry.model_dump(mode="json") for entry in registry.describe()],
            [
                {
                    "capability_id": "code.edit",
                    "implementation_id": "code.edit.alpha",
                    "version": "1.0.0",
                    "modes": ["native"],
                    "platforms": [],
                    "runtime_requirements": [],
                    "native_models": [],
                    "brokered_models": [],
                    "required_permissions": [],
                    "required_packages": [],
                },
                {
                    "capability_id": "code.edit",
                    "implementation_id": "code.edit.zeta",
                    "version": "1.0.0",
                    "modes": ["native"],
                    "platforms": [],
                    "runtime_requirements": [],
                    "native_models": [],
                    "brokered_models": [],
                    "required_permissions": [],
                    "required_packages": [],
                },
            ],
        )

    def test_duplicate_implementation_is_rejected(self):
        registry = CapabilityRegistry()
        implementation = manifest("code.edit.native")
        registry.register(implementation, lambda: ProbeAdapter(True))

        with self.assertRaisesRegex(ValueError, "duplicate implementation"):
            registry.register(implementation, lambda: ProbeAdapter(True))
        with self.assertRaisesRegex(ValueError, "unknown"):
            registry.probe("code.search", context())

    def test_resolution_filters_platform_runtime_model_and_policy(self):
        registry = CapabilityRegistry()
        compatible = manifest(
            "code.edit.compatible",
            platforms=("windows",),
            runtime_requirements=("python-3.15",),
            native_models=("native-model",),
            required_permissions=("project.write",),
        )
        registry.register(compatible, lambda: ProbeAdapter(True))
        registry.register(manifest("code.edit.other-platform", platforms=("linux",)), lambda: ProbeAdapter(True))
        registry.register(manifest("code.edit.other-runtime", runtime_requirements=("node-22",)), lambda: ProbeAdapter(True))
        registry.register(manifest("code.edit.other-model", native_models=("other-model",)), lambda: ProbeAdapter(True))
        registry.register(manifest("code.edit.denied", required_permissions=("network",)), lambda: ProbeAdapter(True))

        runtime = context()
        registry.probe("code.edit", runtime)

        self.assertEqual(
            [result.implementation_id for result in registry.resolve({"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}, runtime)],
            ["code.edit.compatible"],
        )

    def test_package_presence_is_not_readiness(self):
        unavailable = CapabilityRegistry()
        failed_adapter = ProbeAdapter(False)
        unavailable.register(manifest("code.edit.package", required_packages=("editor-package",)), lambda: failed_adapter)
        runtime = context()
        request = {"capability_id": "code.edit", "model_id": "native-model", "mode": "native"}

        self.assertEqual(unavailable.resolve(request, runtime), ())
        self.assertFalse(unavailable.probe("code.edit", runtime)[0].runnable)
        self.assertEqual(unavailable.resolve(request, runtime), ())

        verified = CapabilityRegistry()
        successful_adapter = ProbeAdapter(True)
        verified.register(manifest("code.edit.verified", required_packages=("editor-package",)), lambda: successful_adapter)
        verified.probe("code.edit", runtime)

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
        )
        runtime = context()
        registry.probe("code.edit", runtime)

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
            ["code.edit.dual"],
        )


if __name__ == "__main__":
    unittest.main()
