import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from web_app.core.autonomous_update import UpdateProfile
from web_app.core.canonical import canonical_digest
from web_app.core.git_adapter import VerificationReceipt
from web_app.core.update_launcher import (
    ArtifactMaterializer,
    BuildManifest,
    BuildManifestSigner,
    DockerIsolationRunner,
    IsolationUnavailable,
    PlaywrightBrowserProbe,
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout.strip()


class UpdateIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        git(self.repository, "init", "-b", "main")
        git(self.repository, "config", "user.name", "JSON CODR Tests")
        git(self.repository, "config", "user.email", "tests@example.invalid")
        (self.repository / "web_app").mkdir()
        (self.repository / "web_app" / "version.py").write_text(
            'APP_VERSION = "V1.3.9"\n', encoding="utf-8"
        )
        (self.repository / "server.py").write_text("print('fixture')\n", encoding="utf-8")
        git(self.repository, "add", ".")
        git(self.repository, "commit", "-m", "candidate")
        self.commit = git(self.repository, "rev-parse", "HEAD")
        self.tree = git(self.repository, "rev-parse", f"{self.commit}^{{tree}}")
        self.receipt = VerificationReceipt(
            candidate_id="candidate-1",
            base_sha=self.commit,
            tree_sha=self.tree,
            profile_digest="sha256:" + "8" * 64,
            checks=("unit",),
            verified_at="2026-11-24T00:00:00+00:00",
            verifier_credential_id="verifier-1",
            signature="hmac-sha256:" + "9" * 64,
        )
        self.profile = UpdateProfile(
            profile_id="self-update",
            repository_root=str(self.repository),
            branch="main",
            expected_remote_sha=self.commit,
            mandatory_checks=("unit",),
            allowed_repository_roots=(str(self.repository),),
            expected_version="V1.3.9",
            launch_argv=("python3", "server.py", "{host}", "{port}"),
            container_image="fixture-image:locked",
            container_port=8000,
            migration_compatibility="backward_compatible",
        )
        self.profile_digest = canonical_digest(self.profile.model_dump(mode="json"))
        self.candidate = SimpleNamespace(
            candidate_id="candidate-1",
            commit_sha=self.commit,
            verification_receipt=self.receipt,
            profile_digest=self.profile_digest,
            worktree=SimpleNamespace(working_root=str(self.repository)),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_materializer_exports_exact_commit_without_git_metadata(self):
        materializer = ArtifactMaterializer(self.root / "artifacts")

        artifact = materializer.materialize(self.candidate, self.profile)

        artifact_root = Path(artifact.root)
        self.assertEqual(artifact.revision, self.commit)
        self.assertEqual(artifact.tree_sha, self.tree)
        self.assertEqual(artifact.version, "V1.3.9")
        self.assertFalse((artifact_root / ".git").exists())
        self.assertEqual((artifact_root / "server.py").read_text(encoding="utf-8"), "print('fixture')\n")
        self.assertFalse(any(path.is_symlink() for path in artifact_root.rglob("*")))

    def test_materializer_rejects_head_tree_or_profile_binding_mismatch(self):
        materializer = ArtifactMaterializer(self.root / "artifacts")
        wrong_tree = self.receipt.model_copy(update={"tree_sha": "f" * 40})
        candidate = SimpleNamespace(**{**self.candidate.__dict__, "verification_receipt": wrong_tree})

        with self.assertRaisesRegex(PermissionError, "tree"):
            materializer.materialize(candidate, self.profile)

        wrong_profile = SimpleNamespace(**{**self.candidate.__dict__, "profile_digest": "sha256:" + "0" * 64})
        with self.assertRaisesRegex(PermissionError, "profile"):
            materializer.materialize(wrong_profile, self.profile)

    def test_materializer_never_replaces_an_existing_immutable_artifact(self):
        materializer = ArtifactMaterializer(self.root / "artifacts")
        artifact = materializer.materialize(self.candidate, self.profile)
        Path(artifact.root, "server.py").write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(PermissionError, "existing immutable"):
            materializer.materialize(self.candidate, self.profile)

        self.assertEqual(Path(artifact.root, "server.py").read_text(encoding="utf-8"), "tampered\n")

    def test_signed_manifest_binds_tree_version_migration_and_profile(self):
        signer = BuildManifestSigner(key=b"k" * 32)
        manifest = BuildManifest(
            candidate_id="candidate-1",
            revision=self.commit,
            tree_sha=self.tree,
            update_profile_digest=self.profile_digest,
            verification_profile_digest=self.receipt.profile_digest,
            version="V1.3.9",
            migration_compatibility="backward_compatible",
            artifact_root=str(self.root / "artifact"),
            artifact_digest="d" * 64,
            container_image="fixture-image:locked",
            launch_argv=("python3", "server.py"),
            container_port=8000,
        )

        signed = signer.sign(manifest)

        self.assertTrue(signer.validate(signed))
        self.assertFalse(signer.validate(signed.model_copy(update={"version": "V9.9.9"})))
        self.assertFalse(signer.validate(signed.model_copy(update={"migration_compatibility": "irreversible"})))

    def test_docker_runner_uses_only_restricted_readonly_artifact_and_disposable_data_mounts(self):
        calls = []

        def run(arguments, **kwargs):
            calls.append(list(arguments))
            if "network" in arguments and "create" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "network-id\n", "")
            if "run" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "container-id\n", "")
            if "inspect" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "sha256:" + "c" * 64 + "\n", "")
            return subprocess.CompletedProcess(arguments, 0, "", "")

        artifact = self.root / "artifact"
        data = self.root / "data"
        artifact.mkdir()
        data.mkdir()
        runner = DockerIsolationRunner(
            distro="Ubuntu", command_runner=run,
            path_translator=lambda path: "/isolated/" + Path(path).name,
        )

        process = runner.launch(
            artifact_root=artifact,
            data_root=data,
            image="fixture-image:locked",
            command=("python3", "server.py"),
            host_port=43210,
            container_port=8000,
            environment={"JSON_CODR_REVISION": self.commit},
            artifact_digest=ArtifactMaterializer._directory_digest(artifact),
        )

        docker_run = next(call for call in calls if "run" in call)
        flattened = " ".join(docker_run)
        self.assertIn("--read-only", docker_run)
        self.assertIn("--cap-drop", docker_run)
        self.assertIn("ALL", docker_run)
        self.assertIn("no-new-privileges", flattened)
        self.assertIn("--user", docker_run)
        self.assertIn("65534:65534", docker_run)
        self.assertIn("/isolated/artifact:/app:ro", docker_run)
        self.assertIn("/isolated/data:/data:rw", docker_run)
        self.assertNotIn(str(self.repository), flattened)
        self.assertNotIn("GH_TOKEN", flattened)
        self.assertIn("sha256:" + "c" * 64, docker_run)
        self.assertNotIn("fixture-image:locked", docker_run)
        self.assertEqual(process.container_id, "container-id")

    def test_docker_runner_fails_closed_when_engine_or_image_is_unavailable(self):
        def unavailable(arguments, **kwargs):
            return subprocess.CompletedProcess(arguments, 1, "", "docker unavailable")

        runner = DockerIsolationRunner(
            distro="Ubuntu", command_runner=unavailable,
            path_translator=lambda path: "/isolated/" + Path(path).name,
        )
        artifact = self.root / "artifact"
        data = self.root / "data"
        artifact.mkdir()
        data.mkdir()

        with self.assertRaises(IsolationUnavailable):
            runner.launch(
                artifact_root=artifact, data_root=data, image="missing:locked",
                command=("python3", "server.py"), host_port=43210,
                container_port=8000, environment={},
                artifact_digest=ArtifactMaterializer._directory_digest(artifact),
            )

    def test_real_browser_probe_captures_console_and_page_errors(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<script>console.error('fatal-console'); throw new Error('fatal-page')</script>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_arguments):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = PlaywrightBrowserProbe()(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

        self.assertTrue(result["loaded"])
        self.assertTrue(any("fatal-console" in item for item in result["fatal_errors"]))
        self.assertTrue(any("fatal-page" in item for item in result["fatal_errors"]))


if __name__ == "__main__":
    unittest.main()
