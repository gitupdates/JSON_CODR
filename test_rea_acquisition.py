import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_app.core.rea_acquisition import ReaAcquirer, ReaReleaseMetadata
from web_app.core.rea_provider_state import ReaProviderStore


class RecordingInstaller:
    def __init__(self):
        self.calls = []

    def install(self, metadata, installation):
        self.calls.append((metadata, installation))
        package = installation / "node_modules" / "rea-agents"
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"name":"rea-agents","version":"6.9.0"}', encoding="utf-8")
        (installation / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "node_modules/rea-agents": {
                "version": metadata.version, "integrity": metadata.integrity, "resolved": metadata.tarball
            }
        }}), encoding="utf-8")


class ReaAcquisitionTests(unittest.TestCase):
    def test_tree_digest_covers_native_payload_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package-lock.json").write_text('{"packages":{"node_modules/native":{"integrity":"sha512-real"}}}', encoding="utf-8")
            native = root / "node_modules" / "native" / "addon.node"
            native.parent.mkdir(parents=True)
            native.write_bytes(b"native-payload")
            digest = ReaAcquirer._tree_digest(root)
            native.write_bytes(b"changed-payload")
            changed = ReaAcquirer._tree_digest(root)

            self.assertTrue(digest.startswith("sha256:"))
            self.assertNotEqual(digest, changed)

    def test_exact_trusted_release_promotes_to_immutable_version_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            installer = RecordingInstaller()
            acquirer = ReaAcquirer(root, store, installer)
            metadata = ReaReleaseMetadata(
                package="rea-agents", version="6.9.0", integrity="sha512-real",
                registry="https://registry.npmjs.org", tarball="https://registry.npmjs.org/rea-agents/-/rea-agents-6.9.0.tgz",
            )

            version_root = acquirer.acquire(metadata)

            self.assertEqual(version_root, root / "versions" / "6.9.0")
            self.assertTrue((version_root / "manifest.json").is_file())
            self.assertTrue((version_root / "installation" / "node_modules" / "rea-agents" / "package.json").is_file())
            self.assertEqual(store.candidate("6.9.0").state, "staged")
            self.assertEqual(len(installer.calls), 1)
            store.close()

    def test_rejects_untrusted_or_incomplete_metadata_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            installer = RecordingInstaller()
            acquirer = ReaAcquirer(root, store, installer)

            for metadata in (
                ReaReleaseMetadata("other", "6.9.0", "sha512-x", "https://registry.npmjs.org", "https://x"),
                ReaReleaseMetadata("rea-agents", "6.9.0", "", "https://registry.npmjs.org", "https://x"),
                ReaReleaseMetadata("rea-agents", "6.9.0", "sha512-x", "https://evil.example", "https://x"),
            ):
                with self.assertRaises(ValueError):
                    acquirer.acquire(metadata)
            self.assertEqual(installer.calls, [])
            store.close()

    def test_existing_package_identity_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            installer = RecordingInstaller()
            acquirer = ReaAcquirer(root, store, installer)
            metadata = ReaReleaseMetadata("rea-agents", "6.9.0", "sha512-x", "https://registry.npmjs.org", "https://x")
            first = acquirer.acquire(metadata)
            second = acquirer.acquire(metadata)
            self.assertEqual(first, second)
            self.assertEqual(len(installer.calls), 1)
            store.close()

    def test_interrupted_acquisition_can_be_retried_after_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReaProviderStore(root / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-x", source="https://registry.npmjs.org")
            store.transition("6.9.0", "acquiring", expected_revision=candidate.revision)
            store.recover()
            installer = RecordingInstaller()
            metadata = ReaReleaseMetadata("rea-agents", "6.9.0", "sha512-x", "https://registry.npmjs.org", "https://x")

            version_root = ReaAcquirer(root, store, installer).acquire(metadata)

            self.assertTrue(version_root.is_dir())
            self.assertEqual(store.candidate("6.9.0").state, "staged")
            store.close()


if __name__ == "__main__":
    unittest.main()
