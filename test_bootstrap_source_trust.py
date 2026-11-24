import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE = ROOT / "scripts" / "bootstrap" / "SourceTrust.psm1"


class SourceTrustTests(unittest.TestCase):
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
