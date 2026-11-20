import io
import tempfile
import unittest
from pathlib import Path


class FakeApi:
    def __init__(self):
        self.created = []
        self.polls = 0
        self.exported = []

    def create(self, payload):
        self.created.append(payload)
        return {"run_id": "run-1", "status": "queued"}

    def get(self, run_id):
        self.polls += 1
        return {"run_id": run_id, "status": "completed", "results": []}

    def export(self, run_id, format_name):
        self.exported.append((run_id, format_name))
        return '{"run_id":"run-1"}'


class ModelJuryCliTests(unittest.TestCase):
    def run_case(self, source_args, stdin=""):
        from model_jury_cli import execute
        api = FakeApi()
        output = io.StringIO()
        execute(["--session", "session-1", *source_args], api=api, stdin=io.StringIO(stdin), stdout=output)
        self.assertEqual(api.created[0]["profile"], "code_jury")
        self.assertEqual(api.exported, [("run-1", "json")])
        self.assertEqual(api.polls, 1)
        return api.created[0]["prompt"]

    def test_inline_code_uses_canonical_code_jury_run(self):
        self.assertEqual(self.run_case(["--code", "print('ok')"]), "print('ok')")

    def test_file_uses_canonical_code_jury_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text("x = 1", encoding="utf-8")
            self.assertEqual(self.run_case(["--file", str(path)]), "x = 1")

    def test_stdin_uses_canonical_code_jury_run(self):
        self.assertEqual(self.run_case([], stdin="stdin code"), "stdin code")


if __name__ == "__main__":
    unittest.main()
