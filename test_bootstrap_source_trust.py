import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE = ROOT / "scripts" / "bootstrap" / "SourceTrust.psm1"
WORKSPACE_STATE_MODULE = ROOT / "scripts" / "bootstrap" / "WorkspaceState.psm1"


class SourceTrustTests(unittest.TestCase):
    def test_workspace_state_migration_preserves_content_without_executing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            data_root = Path(temporary) / "data"
            scratch = root / ".tmp"
            scratch.mkdir(parents=True)
            marker = Path(temporary) / "executed.txt"
            payload = scratch / "payload.py"
            payload.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
                encoding="utf-8",
            )
            payload_bytes = payload.read_bytes()
            nested = scratch / "logs" / "server.log"
            nested.parent.mkdir()
            nested.write_text("preserve me\n", encoding="utf-8")

            process = self._workspace_migration(root, data_root)

            self.assertEqual(process.returncode, 0, process.stderr)
            receipt = json.loads(process.stdout)
            self.assertEqual(receipt["status"], "migrated")
            self.assertFalse(scratch.exists())
            self.assertFalse(marker.exists())
            destination = Path(receipt["destination"])
            self.assertTrue(destination.name.startswith("workspace-tmp-"), receipt)
            self.assertEqual((destination / "payload.py").read_bytes(), payload_bytes)
            self.assertEqual((destination / "logs" / "server.log").read_text(encoding="utf-8"), "preserve me\n")
            self.assertTrue(Path(receipt["receipt_path"]).is_file())
            self.assertEqual(len(receipt["files"]), 2)
            self.assertTrue(all(item["source_sha256"] == item["destination_sha256"] for item in receipt["files"]))

    def test_workspace_state_migration_rejects_reparse_points(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            data_root = Path(temporary) / "data"
            outside = Path(temporary) / "outside"
            scratch = root / ".tmp"
            scratch.mkdir(parents=True)
            outside.mkdir()
            junction = scratch / "escape"
            command = (
                f"New-Item -ItemType Junction -Path '{junction}' -Target '{outside}' | Out-Null"
            )
            created = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            process = self._workspace_migration(root, data_root)

            self.assertNotEqual(process.returncode, 0)
            self.assertIn("reparse", process.stderr.casefold())
            self.assertTrue(scratch.exists())
            self.assertFalse((data_root / "migration-receipts").exists())

    def test_workspace_state_hash_verification_rejects_changed_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            destination = Path(temporary) / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "evidence.log").write_text("original\n", encoding="utf-8")
            (destination / "evidence.log").write_text("changed\n", encoding="utf-8")
            environment = dict(os.environ)
            environment.update({
                "JSON_CODR_WORKSPACE_STATE_MODULE": str(WORKSPACE_STATE_MODULE),
                "JSON_CODR_MIGRATION_SOURCE": str(source),
                "JSON_CODR_MIGRATION_DESTINATION": str(destination),
            })
            command = (
                "Import-Module -Name $env:JSON_CODR_WORKSPACE_STATE_MODULE -Force; "
                "Test-JsonCodrMigrationContent -Source $env:JSON_CODR_MIGRATION_SOURCE "
                "-Destination $env:JSON_CODR_MIGRATION_DESTINATION | ConvertTo-Json -Compress"
            )

            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )

            self.assertNotEqual(process.returncode, 0)
            self.assertIn("hash", process.stderr.casefold())

    def test_workspace_state_migration_recovers_an_interrupted_staging_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            data_root = Path(temporary) / "data"
            scratch = root / ".tmp"
            scratch.mkdir(parents=True)
            (scratch / "state.log").write_text("complete\n", encoding="utf-8")
            stale = data_root / "workspace-migrations" / ".interrupted.staging"
            stale.mkdir(parents=True)
            (stale / "partial.log").write_text("partial\n", encoding="utf-8")

            process = self._workspace_migration(root, data_root)

            self.assertEqual(process.returncode, 0, process.stderr)
            receipt = json.loads(process.stdout)
            self.assertFalse(stale.exists())
            self.assertEqual(
                (Path(receipt["destination"]) / "state.log").read_text(encoding="utf-8"),
                "complete\n",
            )

    def test_clean_commit_reachable_from_origin_is_trusted(self):
        """Removing the remote reachability proof must make a normal bootstrap untrusted."""
        with self._repository() as repository:
            evidence = self._evidence(repository)

            self.assertEqual(evidence["trustState"], "trusted")
            self.assertTrue(evidence["normalizedRemote"])
            self.assertFalse(str(evidence["normalizedRemote"]).endswith(".git"))
            self.assertRegex(evidence["commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(evidence["tree"], r"^[0-9a-f]{40}$")
            self.assertRegex(evidence["manifestDigest"], r"^[0-9a-f]{64}$")
            self.assertEqual(evidence["reason"], "clean commit is reachable from origin")

    def test_dirty_worktree_is_untrusted(self):
        """Ignoring local changes would let an unreviewed tree claim trusted source evidence."""
        with self._repository() as repository:
            (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")

            evidence = self._evidence(repository)

            self.assertEqual(evidence["trustState"], "untrusted")
            self.assertEqual(evidence["reason"], "working tree is dirty")

    def test_detached_commit_not_reachable_from_origin_is_untrusted(self):
        """Treating a detached local-only commit as trusted breaks the remote provenance boundary."""
        with self._repository() as repository:
            self._git(repository, "checkout", "--detach")
            (repository / "tracked.txt").write_text("detached\n", encoding="utf-8")
            self._git(repository, "add", "tracked.txt")
            self._git(repository, "commit", "-m", "detached")

            evidence = self._evidence(repository)

            self.assertEqual(evidence["trustState"], "untrusted")
            self.assertEqual(evidence["reason"], "commit is not reachable from origin")

    def test_remote_other_than_origin_is_untrusted(self):
        """Accepting an arbitrary remote name would bypass the configured trusted-source role."""
        with self._repository(remote_name="upstream") as repository:
            evidence = self._evidence(repository)

            self.assertEqual(evidence["trustState"], "untrusted")
            self.assertEqual(evidence["reason"], "trusted remote 'origin' is not configured")

    def test_ssh_origin_is_normalized_without_transport_or_git_suffix(self):
        """Receipt remote identity must not retain mutable transport spelling."""
        with self._repository() as repository:
            self._git(repository, "remote", "set-url", "origin", "git@github.com:example/JSON_CODR.git")

            evidence = self._evidence(repository)

            self.assertEqual(evidence["trustState"], "trusted")
            self.assertEqual(evidence["normalizedRemote"], "github.com/example/JSON_CODR")

    def test_source_without_git_metadata_is_untrusted(self):
        """A ZIP-style source must not receive a normal trusted receipt."""
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self._evidence(Path(temporary))

            self.assertEqual(evidence["trustState"], "untrusted")
            self.assertEqual(evidence["reason"], "no Git repository found")

    def test_development_source_override_is_visibly_unverified(self):
        """The development escape hatch must never be indistinguishable from trusted source."""
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self._evidence(Path(temporary), development_source=True)

            self.assertEqual(evidence["trustState"], "development")
            self.assertEqual(evidence["reason"], "development source override requested")
            self.assertIsNone(evidence["normalizedRemote"])
            self.assertIsNone(evidence["commit"])
            self.assertIsNone(evidence["tree"])
            self.assertRegex(evidence["manifestDigest"], r"^[0-9a-f]{64}$")

    def test_source_paths_with_spaces_and_non_ascii_characters_are_supported(self):
        """Quoting or encoding bugs must not change the trust result for valid Windows paths."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source space-ž"
            with self._repository(root=root) as repository:
                evidence = self._evidence(repository)

            self.assertEqual(evidence["trustState"], "trusted")

    def _evidence(self, repository: Path, development_source: bool = False) -> dict[str, object]:
        environment = dict(os.environ)
        environment["JSON_CODR_SOURCE_TRUST_MODULE"] = str(MODULE)
        environment["JSON_CODR_SOURCE_TRUST_ROOT"] = str(repository)
        environment["JSON_CODR_DEVELOPMENT_SOURCE"] = "True" if development_source else "False"
        command = (
            "Import-Module -Name $env:JSON_CODR_SOURCE_TRUST_MODULE -Force; "
            "Get-JsonCodrSourceEvidence -Root $env:JSON_CODR_SOURCE_TRUST_ROOT "
            "-DevelopmentSource:([System.Convert]::ToBoolean($env:JSON_CODR_DEVELOPMENT_SOURCE)) | "
            "ConvertTo-Json -Compress"
        )
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def _workspace_migration(self, root: Path, data_root: Path) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.update({
            "JSON_CODR_WORKSPACE_STATE_MODULE": str(WORKSPACE_STATE_MODULE),
            "JSON_CODR_WORKSPACE_STATE_ROOT": str(root),
            "JSON_CODR_WORKSPACE_STATE_DATA_ROOT": str(data_root),
        })
        command = (
            "Import-Module -Name $env:JSON_CODR_WORKSPACE_STATE_MODULE -Force; "
            "Move-JsonCodrWorkspaceState -Root $env:JSON_CODR_WORKSPACE_STATE_ROOT "
            "-DataRoot $env:JSON_CODR_WORKSPACE_STATE_DATA_ROOT | ConvertTo-Json -Depth 8 -Compress"
        )
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )

    def _repository(self, root: Path | None = None, remote_name: str = "origin"):
        temporary = tempfile.TemporaryDirectory()
        repository = root or Path(temporary.name) / "source"
        repository.mkdir(parents=True)
        self._git(repository, "init", "-b", "main")
        self._git(repository, "config", "user.email", "test@example.invalid")
        self._git(repository, "config", "user.name", "Source Trust Test")
        (repository / "tracked.txt").write_text("clean\n", encoding="utf-8")
        self._git(repository, "add", "tracked.txt")
        self._git(repository, "commit", "-m", "initial")
        remote = Path(temporary.name) / "trusted remote.git"
        self._git(Path(temporary.name), "init", "--bare", str(remote))
        self._git(repository, "remote", "add", remote_name, str(remote))
        self._git(repository, "push", remote_name, "HEAD:main")
        self._git(repository, "fetch", remote_name)

        class _RepositoryContext:
            def __enter__(_self):
                return repository

            def __exit__(_self, *_args):
                temporary.cleanup()

        return _RepositoryContext()

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
