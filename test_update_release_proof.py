import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

from json_codr_launcher import (
    DockerPublicRunner,
    PointerStore,
    StableSupervisor,
    _http_probe,
    health_receipt_validator,
    _artifact_digest,
)
from web_app.core.autonomous_update import UpdateProfile
from web_app.core.canonical import canonical_digest
from web_app.core.git_adapter import VerificationReceipt
from web_app.core.update_launcher import (
    ArtifactMaterializer,
    BuildManifestSigner,
    DockerIsolationRunner,
    HealthReceiptSigner,
    PlaywrightBrowserProbe,
    UpdateLauncher,
)


PROOF_IMAGE = os.environ.get(
    "JSON_CODR_PROOF_IMAGE",
    "vsc-open_forge-v0.2.0-ea2158e095d10ffcd39729155293acc2ff880d233dedaec1fbe5d3e9dff37510-features-uid:latest",
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()


def free_port() -> int:
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def docker_available() -> bool:
    result = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", "docker", "image", "inspect", PROOF_IMAGE],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def proof_image_id() -> str:
    return subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", "docker", "image", "inspect",
         "--format", "{{.Id}}", PROOF_IMAGE],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


SERVER_SOURCE = r'''
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

revision = os.environ["JSON_CODR_REVISION"]
version = os.environ["JSON_CODR_EXPECTED_VERSION"]
instance = os.environ["JSON_CODR_INSTANCE_ID"]
started = os.environ["JSON_CODR_STARTED_AT"]
manifest = os.environ["JSON_CODR_ARTIFACT_MANIFEST"]
port = int(os.environ["JSON_CODR_PORT"])

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            payload = {
                "status": "ready", "revision": revision, "app_version": version,
                "health_nonce": self.headers.get("X-JSON-CODR-Health-Nonce"),
                "instance_id": instance, "started_at": started,
                "manifest_digest": manifest, "uid": os.getuid(),
                "host_home_visible": os.path.exists("/mnt/c/Users/BLACK"),
                "git_metadata_visible": os.path.exists("/app/.git"),
            }
            body = json.dumps(payload).encode()
            kind = "application/json"
        elif self.path == "/openapi.json":
            body = json.dumps({"openapi": "3.1.0"}).encode()
            kind = "application/json"
        elif self.path == "/":
            body = b"<!doctype html><title>isolated update proof</title><main>ready</main>"
            kind = "text/html"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *_args): pass

ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
'''


class DirectSupervisorClient:
    def __init__(self, supervisor):
        self.supervisor = supervisor

    def activate(self, health, target):
        return self.supervisor.activate({
            "activation_id": f"activation-{health.candidate_id}",
            "expected_generation": self.supervisor.store.load()["generation"],
            "health_receipt": health.model_dump(mode="json"),
            "target_pointer": dict(target),
        })

    def rollback(self, activation_id):
        return self.supervisor.rollback(activation_id)


@unittest.skipUnless(docker_available(), f"WSL Docker proof image is unavailable: {PROOF_IMAGE}")
class IsolatedReleaseProofTests(unittest.TestCase):
    def test_real_container_health_supervisor_switch_browser_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher_root = root / "launcher"
            repository = root / "candidate-repository"
            repository.mkdir()
            git(repository, "init", "-b", "main")
            git(repository, "config", "user.name", "Release Proof")
            git(repository, "config", "user.email", "proof@example.invalid")
            (repository / "web_app").mkdir()
            (repository / "web_app" / "version.py").write_text(
                'APP_VERSION = "V1.4.0"\n', encoding="utf-8"
            )
            (repository / "server.py").write_text(SERVER_SOURCE, encoding="utf-8")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "isolated V1.4.0 candidate")
            revision = git(repository, "rev-parse", "HEAD")
            tree = git(repository, "rev-parse", f"{revision}^{{tree}}")

            initial_root = root / "initial-artifact"
            initial_data = root / "initial-data"
            initial_root.mkdir()
            initial_data.mkdir()
            (initial_root / "server.py").write_text(SERVER_SOURCE, encoding="utf-8")
            initial_revision = "1" * 40
            initial_pointer = {
                "schema_version": 1, "generation": 0,
                "revision": initial_revision, "tree_sha": initial_revision,
                "root": str(initial_root), "version": "V1.3.9",
                "runner": "docker", "launch_argv": ["python3", "server.py"],
                "manifest_digest": "sha256:" + "1" * 64,
                "manifest_signature": "hmac-sha256:" + "1" * 64,
                "artifact_digest": _artifact_digest(initial_root),
                "container_image": proof_image_id(), "container_port": 8000,
                "data_root": str(initial_data), "activated_at": datetime.now(UTC).isoformat(),
                "previous_revision": None,
            }
            key = b"release-proof-key".ljust(32, b"-")
            public_port = free_port()
            self.assertNotEqual(public_port, 8765)
            store = PointerStore(launcher_root / "pointer" / "active-build.json")
            supervisor = StableSupervisor(
                store,
                runner=DockerPublicRunner(distro="Ubuntu"),
                probe=_http_probe,
                host="127.0.0.1",
                port=public_port,
                receipt_validator=health_receipt_validator(key),
            )
            launcher = None
            try:
                supervisor.initialize(initial_pointer)
                profile = UpdateProfile(
                    profile_id="self-update", repository_root=str(repository),
                    branch="main", expected_remote_sha=revision,
                    mandatory_checks=("release-proof",),
                    allowed_repository_roots=(str(repository),),
                    expected_version="V1.4.0",
                    launch_argv=("python3", "server.py"),
                    container_image=PROOF_IMAGE, container_port=8000,
                    migration_compatibility="backward_compatible",
                    startup_timeout_seconds=20,
                )
                candidate = SimpleNamespace(
                    candidate_id="candidate-release-proof", commit_sha=revision,
                    profile_digest=canonical_digest(profile.model_dump(mode="json")),
                    verification_receipt=VerificationReceipt(
                        candidate_id="candidate-release-proof", base_sha=revision,
                        tree_sha=tree, profile_digest="sha256:" + "a" * 64,
                        checks=("release-proof",), verified_at=datetime.now(UTC),
                        verifier_credential_id="release-proof",
                        signature="hmac-sha256:" + "b" * 64,
                    ),
                    worktree=SimpleNamespace(working_root=str(repository)),
                )
                launcher = UpdateLauncher(
                    launcher_root,
                    materializer=ArtifactMaterializer(launcher_root / "artifacts"),
                    isolation_runner=DockerIsolationRunner(distro="Ubuntu"),
                    manifest_signer=BuildManifestSigner(key=key),
                    health_signer=HealthReceiptSigner(key),
                    supervisor_client=DirectSupervisorClient(supervisor),
                    browser_probe=PlaywrightBrowserProbe(timeout_ms=15_000),
                )

                health = launcher.launch_candidate(candidate, profile)
                with urlopen(Request(
                    f"http://127.0.0.1:{health.port}/api/health",
                    headers={"X-JSON-CODR-Health-Nonce": "boundary-proof"},
                ), timeout=5) as response:
                    boundary = json.loads(response.read())
                self.assertEqual(boundary["uid"], 65534)
                self.assertFalse(boundary["host_home_visible"])
                self.assertFalse(boundary["git_metadata_visible"])

                activation = launcher.activate(health)
                with urlopen(Request(
                    f"http://127.0.0.1:{public_port}/api/health",
                    headers={"X-JSON-CODR-Health-Nonce": "public-proof"},
                ), timeout=5) as response:
                    active = json.loads(response.read())
                self.assertEqual(active["revision"], revision)
                self.assertEqual(active["app_version"], "V1.4.0")
                self.assertEqual(PlaywrightBrowserProbe()(f"http://127.0.0.1:{public_port}")["fatal_errors"], ())

                rollback = launcher.rollback(activation["activation_id"])
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with urlopen(Request(
                            f"http://127.0.0.1:{public_port}/api/health",
                            headers={"X-JSON-CODR-Health-Nonce": "rollback-proof"},
                        ), timeout=1) as response:
                            restored = json.loads(response.read())
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.1)
                self.assertEqual(rollback["restored_revision"], initial_revision)
                self.assertEqual(restored["revision"], initial_revision)
            finally:
                if launcher is not None:
                    launcher.close()
                supervisor.shutdown()


if __name__ == "__main__":
    unittest.main()
