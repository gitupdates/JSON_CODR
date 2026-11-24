import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from web_app.core.migration import MigrationService
from web_app.core.identity import IdentityService


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class MigrationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.source = root / "beta"
        self.destination = root / "alpha"
        (self.source / "sessions" / ("a" * 32)).mkdir(parents=True)
        (self.source / "sessions" / ("b" * 32)).mkdir(parents=True)
        (self.source / "skill_library" / "sources").mkdir(parents=True)
        (self.source / "imports").mkdir()
        (self.source / "sessions" / ("a" * 32) / "manifest.json").write_text(
            json.dumps({"id": "a" * 32, "messages": [{"role": "user", "content": "useful"}]}), encoding="utf-8"
        )
        (self.source / "sessions" / ("b" * 32) / "manifest.json").write_text("{bad", encoding="utf-8")
        (self.source / "skill_library" / "catalog.json").write_text('[{"id":"skill"}]', encoding="utf-8")
        (self.source / "settings.json").write_text(
            json.dumps({"ui": {"theme": "light"}, "api_key": "never-copy"}), encoding="utf-8"
        )
        (self.source / "hardware-benchmarks.json").write_text("[]", encoding="utf-8")
        (self.source / "imports" / "resource.txt").write_text("resource", encoding="utf-8")
        (self.source / "git-broker-grants.json").write_text(
            json.dumps([{"project_root": "D:/project", "profile": "broker"}]), encoding="utf-8"
        )
        (self.source / "coding-agent-grants.json").write_text(
            json.dumps([{"tool": "continue", "project_root": "D:/project"}]), encoding="utf-8"
        )
        (self.source / "secrets").write_text("credential", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_copy_on_write_migration_preserves_useful_data_and_excludes_secrets(self):
        before = tree_digest(self.source)
        service = MigrationService()
        inspection = service.inspect(self.source)
        self.assertIn("settings.json", inspection.candidates)
        report = service.migrate(self.source, self.destination)

        self.assertEqual(tree_digest(self.source), before)
        self.assertTrue(service.verify(report))
        settings = json.loads((self.destination / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["ui"]["theme"], "light")
        self.assertNotIn("api_key", settings)
        self.assertTrue((self.destination / "skill_library" / "catalog.json").is_file())
        self.assertTrue((self.destination / "sessions" / ("a" * 32) / "manifest.json").is_file())
        self.assertTrue((self.destination / "imports" / "resource.txt").is_file())
        self.assertTrue((self.destination / "migration" / "permissions.json").is_file())
        self.assertTrue((self.destination / "migration-archive" / "coding-agent-grants.json").is_file())
        self.assertFalse((self.destination / "coding-agent-grants.json").exists())
        self.assertFalse((self.destination / "secrets").exists())
        self.assertTrue(any("manifest.json" in item for item in report.malformed))
        identity = IdentityService(self.destination)
        self.assertEqual(identity.list_users()[0].username, "Administrator")
        self.assertFalse(identity.development_bypass().enabled)

        service.rollback(report)
        self.assertFalse(self.destination.exists())
        self.assertEqual(tree_digest(self.source), before)


if __name__ == "__main__":
    unittest.main()
