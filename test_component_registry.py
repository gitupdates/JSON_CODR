import tempfile
import unittest
from pathlib import Path

from web_app.core.component_registry import ComponentRegistry, ComponentRequest, ComponentScope


class ComponentRegistryTests(unittest.TestCase):
    def request(self, source="https://example.test/tool.git", *, scope=ComponentScope.global_, project_id=None):
        return ComponentRequest(source_kind="git", source=source, scope=scope, project_id=project_id)

    def verified_generation(self, registry, request=None, *, evidence="sha256:" + "1" * 64):
        plan = registry.plan(request or self.request())
        generation = registry.stage(plan)
        return registry.record_probe(
            generation.component_id,
            generation.generation,
            succeeded=True,
            evidence_digest=evidence,
        )

    def test_global_activation_survives_restart_and_resolves_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "registry.sqlite"
            registry = ComponentRegistry(database)
            generation = self.verified_generation(registry)
            registry.activate(generation.component_id, generation.generation, scope=ComponentScope.global_)
            registry.close()

            restarted = ComponentRegistry(database)
            resolved = restarted.resolve(generation.component_id, "project-a")
            restarted.close()

            self.assertEqual(resolved.generation, generation.generation)
            self.assertEqual(resolved.scope, ComponentScope.global_)

    def test_project_private_activation_does_not_leak_and_override_is_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ComponentRegistry(Path(directory) / "registry.sqlite")
            global_generation = self.verified_generation(registry)
            registry.activate(global_generation.component_id, global_generation.generation, scope=ComponentScope.global_)
            private_generation = self.verified_generation(
                registry,
                self.request("https://example.test/private.git", scope=ComponentScope.project, project_id="project-a"),
                evidence="sha256:" + "2" * 64,
            )
            registry.activate(
                private_generation.component_id,
                private_generation.generation,
                scope=ComponentScope.project,
                project_id="project-a",
            )
            override = self.verified_generation(
                registry,
                self.request("https://example.test/tool.git"),
                evidence="sha256:" + "3" * 64,
            )
            registry.activate(
                override.component_id,
                override.generation,
                scope=ComponentScope.project,
                project_id="project-a",
            )

            self.assertEqual(registry.resolve(global_generation.component_id, "project-a").generation, override.generation)
            self.assertEqual(registry.resolve(global_generation.component_id, "project-b").generation, global_generation.generation)
            self.assertIsNone(registry.resolve(private_generation.component_id, "project-b"))
            registry.disable(global_generation.component_id, scope=ComponentScope.project, project_id="project-a")
            self.assertEqual(registry.resolve(global_generation.component_id, "project-a").generation, global_generation.generation)
            registry.close()

    def test_failed_probe_cannot_activate(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ComponentRegistry(Path(directory) / "registry.sqlite")
            plan = registry.plan(self.request())
            generation = registry.stage(plan)
            registry.record_probe(
                generation.component_id,
                generation.generation,
                succeeded=False,
                evidence_digest="sha256:" + "4" * 64,
                reason="probe failed",
            )

            with self.assertRaisesRegex(PermissionError, "verified"):
                registry.activate(generation.component_id, generation.generation, scope=ComponentScope.global_)
            self.assertIsNone(registry.resolve(generation.component_id, "project-a"))
            registry.close()

    def test_active_lease_pins_generation_during_upgrade_and_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ComponentRegistry(Path(directory) / "registry.sqlite")
            first = self.verified_generation(registry)
            registry.activate(first.component_id, first.generation, scope=ComponentScope.global_)
            lease = registry.acquire_lease(first.component_id, "project-a")
            second = self.verified_generation(registry, evidence="sha256:" + "5" * 64)
            registry.activate(second.component_id, second.generation, scope=ComponentScope.global_)

            with self.assertRaisesRegex(PermissionError, "leased"):
                registry.remove(first.component_id, first.generation)
            registry.release_lease(lease.lease_id)
            registry.remove(first.component_id, first.generation)
            registry.close()

    def test_recovery_quarantines_interrupted_staging_without_replacing_active(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ComponentRegistry(Path(directory) / "registry.sqlite")
            active = self.verified_generation(registry)
            registry.activate(active.component_id, active.generation, scope=ComponentScope.global_)
            interrupted = registry.stage(registry.plan(self.request("https://example.test/interrupted.git")))

            recovered = registry.recover()

            self.assertEqual(recovered[0].component_id, interrupted.component_id)
            self.assertEqual(recovered[0].state, "quarantined")
            self.assertEqual(registry.resolve(active.component_id, "project-a").generation, active.generation)
            registry.close()

    def test_registry_assigns_event_identity_and_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ComponentRegistry(Path(directory) / "registry.sqlite")
            generation = self.verified_generation(registry)
            registry.activate(generation.component_id, generation.generation, scope=ComponentScope.global_)

            events = registry.events()

            self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
            self.assertEqual(len({event.event_id for event in events}), len(events))
            registry.close()


if __name__ == "__main__":
    unittest.main()
