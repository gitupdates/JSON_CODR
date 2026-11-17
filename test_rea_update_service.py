import json
import tempfile
import unittest
from pathlib import Path

from web_app.core.rea_acquisition import ReaReleaseMetadata
from web_app.core.rea_provider_state import ReaProviderStore
from web_app.core.rea_update_service import ReaUpdateService


class FakeAcquirer:
    def __init__(self, root, store):
        self.root = root
        self.store = store

    def acquire(self, metadata):
        version_root = self.root / "versions" / metadata.version
        version_root.mkdir(parents=True)
        candidate = self.store.discover(metadata.version, integrity=metadata.integrity, source=metadata.registry)
        candidate = self.store.transition(metadata.version, "acquiring", expected_revision=candidate.revision)
        self.store.transition(metadata.version, "staged", expected_revision=candidate.revision)
        return version_root


class FakeVerifier:
    def __init__(self, store):
        self.store = store

    async def verify(self, version):
        candidate = self.store.candidate(version)
        candidate = self.store.transition(version, "verifying", expected_revision=candidate.revision)
        self.store.transition(version, "ready", expected_revision=candidate.revision)
        return {"server_version": version}


class ReaUpdateServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovered_immutable_candidate_is_reprobed_without_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-x", source="https://registry.npmjs.org")
            for state in ("acquiring", "staged", "verifying", "quarantined"):
                candidate = store.transition("6.9.0", state, expected_revision=candidate.revision)
            version_root = root / "versions" / "6.9.0"
            installation = version_root / "installation"
            installation.mkdir(parents=True)
            (installation / "package-lock.json").write_text("{}", encoding="utf-8")
            from web_app.core.rea_acquisition import ReaAcquirer
            digest = ReaAcquirer._tree_digest(installation)
            (version_root / "manifest.json").write_text(json.dumps({
                "package": "rea-agents", "version": "6.9.0", "integrity": "sha512-x",
                "registry": "https://registry.npmjs.org", "package_tree_digest": digest,
            }), encoding="utf-8")

            class RefusingAcquirer:
                def acquire(self, metadata):
                    raise AssertionError("immutable candidate was reinstalled")

            service = ReaUpdateService(root, store, RefusingAcquirer(), FakeVerifier(store))
            metadata = ReaReleaseMetadata("rea-agents", "6.9.0", "sha512-x", "https://registry.npmjs.org", "https://x")

            activation = await service.reinstall(metadata)

            self.assertEqual(activation.version, "6.9.0")
            store.close()

    async def test_reinstall_verifies_then_atomically_projects_active_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            service = ReaUpdateService(root, store, FakeAcquirer(root, store), FakeVerifier(store))
            metadata = ReaReleaseMetadata("rea-agents", "6.9.0", "sha512-x", "https://registry.npmjs.org", "https://x")

            activation = await service.reinstall(metadata)

            projection = json.loads((root / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(activation.version, "6.9.0")
            self.assertEqual(projection, {"generation": 1, "version": "6.9.0"})
            store.close()

    async def test_major_change_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            service = ReaUpdateService(root, store, FakeAcquirer(root, store), FakeVerifier(store))
            first = ReaReleaseMetadata("rea-agents", "6.9.0", "sha512-a", "https://registry.npmjs.org", "https://x")
            await service.reinstall(first)
            major = ReaReleaseMetadata("rea-agents", "7.0.0", "sha512-b", "https://registry.npmjs.org", "https://x")

            with self.assertRaises(PermissionError):
                await service.reinstall(major)
            activation = await service.reinstall(major, approved=True)

            self.assertEqual(activation.version, "7.0.0")
            store.close()


if __name__ == "__main__":
    unittest.main()
