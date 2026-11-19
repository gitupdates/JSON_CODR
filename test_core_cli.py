import io
import json
import unittest

from web_app.core.cli import run_cli


class CoreCliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
