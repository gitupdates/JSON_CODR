import io
import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from web_app.core.cli import run_cli


class CoreCliTests(unittest.TestCase):
    def test_auth_commands_do_not_print_raw_credentials(self):
        class Auth:
            def __init__(self):
                self.requested_scopes = None

            def login(self, username, password, requested_scopes=()):
                self.requested_scopes = requested_scopes
                return SimpleNamespace(account=username, label="WORKSTATION · issued", expires_at=datetime(2030, 1, 1, tzinfo=UTC))

            def status(self):
                return SimpleNamespace(username="Administrator", scopes=("lesson.read",))

            def logout(self):
                return None

        output = io.StringIO()
        auth = Auth()
        self.assertEqual(
            run_cli(
                ["auth", "login", "--scope", "git.commit", "--scope", "terminal.write"],
                auth_service=auth,
                stdout=output,
            ),
            0,
        )
        self.assertEqual(auth.requested_scopes, ("git.commit", "terminal.write"))
        self.assertNotIn("token", output.getvalue().casefold())
        self.assertEqual(run_cli(["auth", "status"], auth_service=auth, stdout=output), 0)
        self.assertEqual(run_cli(["auth", "logout"], auth_service=auth, stdout=output), 0)

    def test_run_loads_the_current_cli_token_only_for_bearer_authorization(self):
        class Store:
            def load(self):
                return {"token": "cli-secret"}

        request_headers = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request):
            request_headers.update(dict(request.header_items()))
            return Response(b'{"task_id":"task-1","status":"completed","events":[]}')

        output = io.StringIO()
        with patch("web_app.core.cli.urllib.request.urlopen", urlopen):
            code = run_cli(
                ["run", "--project", ".", "inspect"],
                auth_service=SimpleNamespace(store=Store()),
                stdout=output,
            )
        self.assertEqual(code, 0)
        self.assertEqual(request_headers["Authorization"], "Bearer cli-secret")
        self.assertNotIn("cli-secret", output.getvalue())

    def test_run_fails_closed_when_the_current_cli_token_is_missing(self):
        class Store:
            def load(self):
                raise PermissionError("CLI credential storage is unavailable or corrupt")

        stderr = io.StringIO()
        self.assertEqual(
            run_cli(
                ["run", "--project", ".", "inspect"],
                auth_service=SimpleNamespace(store=Store()),
                stderr=stderr,
            ),
            1,
        )
        self.assertIn("authentication failed", stderr.getvalue())

    def test_json_and_text_outputs_have_deterministic_exit_codes(self):
        completed = {
            "task_id": "task-1",
            "status": "completed",
            "events": [{"event_type": "task.output", "payload": {"text": "done", "token": "hidden"}}],
        }
        output = io.StringIO()
        code = run_cli(
            ["run", "--project", ".", "--output", "json", "inspect"],
            submit=lambda _command: completed,
            stdout=output,
        )
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertNotIn("token", output.getvalue())

        permission = {"task_id": "task-2", "status": "pending", "events": [{"event_type": "task.permission_required", "payload": {}}]}
        self.assertEqual(
            run_cli(
                ["run", "--project", ".", "--output", "text", "push"],
                submit=lambda _command: permission,
                stdout=io.StringIO(),
            ),
            2,
        )
        self.assertEqual(
            run_cli(
                ["run", "--project", ".", "failed"],
                submit=lambda _command: {"task_id": "task-3", "status": "failed", "events": []},
                stdout=io.StringIO(),
            ),
            1,
        )

    def test_stream_json_emits_one_redacted_event_per_line(self):
        output = io.StringIO()
        result = {
            "task_id": "task-1",
            "status": "completed",
            "events": [
                {"event_type": "task.output", "payload": {"text": "one", "secret": "remove"}},
                {"event_type": "task.completed", "payload": {}},
            ],
        }
        code = run_cli(
            ["run", "--project", ".", "--output", "stream-json", "inspect"],
            submit=lambda _command: result,
            stdout=output,
        )
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([line["event_type"] for line in lines], ["task.output", "task.completed"])
        self.assertNotIn("secret", output.getvalue())

    def test_text_output_reports_truthful_hybrid_execution_evidence(self):
        output = io.StringIO()
        result = {
            "task_id": "task-1",
            "status": "completed",
            "events": [{
                "event_type": "capability.completed",
                "payload": {
                    "text": "done",
                    "execution_route": "compatibility",
                    "adapter_id": "rea",
                    "requested_model_id": "legacy:7b",
                    "effective_model_id": "qwen3:4b",
                    "approval_state": "approved",
                    "verification_status": "passed",
                    "retry_count": 1,
                    "rollback_status": "not_required",
                },
            }],
        }
        self.assertEqual(run_cli(["run", "--project", ".", "inspect"], submit=lambda _: result, stdout=output), 0)
        rendered = output.getvalue()
        self.assertIn("compatibility · rea", rendered)
        self.assertIn("legacy:7b → qwen3:4b", rendered)
        self.assertIn("verified passed", rendered)

    def test_status_command_reports_local_only_and_degraded_runtime(self):
        output = io.StringIO()
        status = {
            "local_only": True,
            "health": "degraded",
            "heartbeats": [{"runtime_id": "web", "status": "running", "stale": True}],
            "telemetry": [],
        }
        code = run_cli(["status"], submit=lambda _: status, stdout=output)
        self.assertEqual(code, 1)
        self.assertIn("LOCAL ONLY", output.getvalue())
        self.assertIn("web · stale", output.getvalue())


if __name__ == "__main__":
    unittest.main()
