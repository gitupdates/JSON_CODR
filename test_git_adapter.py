import unittest

from web_app.git_adapter import GitActionAdapter, classify_tool_support_error


class GitActionAdapterTests(unittest.TestCase):
    def test_parses_one_strict_broker_object(self):
        adapter = GitActionAdapter()
        request = adapter.parse(
            '{"schema_version":1,"project_root":"C:/repo","baseline_fingerprint":"abc",'
            '"actions":[{"kind":"status"}]}'
        )
        self.assertEqual(request.actions[0].kind, "status")

    def test_rejects_prose_fences_unknown_fields_and_oversized_output(self):
        adapter = GitActionAdapter(max_response_bytes=1000)
        valid = '{"schema_version":1,"project_root":"C:/repo","baseline_fingerprint":"abc","actions":[{"kind":"status"}]}'
        for response in (f"Here you go: {valid}", f"```json\n{valid}\n```", valid[:-1] + ',"command":"whoami"}'):
            with self.subTest(response=response[:20]):
                with self.assertRaises(ValueError):
                    adapter.parse(response)
        with self.assertRaisesRegex(ValueError, "too large"):
            adapter.parse("x" * 1001)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            adapter.parse('{"schema_version":1,"schema_version":1,"project_root":"C:/repo","baseline_fingerprint":"abc","actions":[{"kind":"status"}]}')

    def test_tool_support_error_routes_to_broker_adapter_without_raw_json(self):
        error = '400 registry.ollama.ai/library/yi-coder:9b-chat does not support tools'
        capability = classify_tool_support_error(error)
        self.assertEqual(capability["mode"], "broker_adapter")
        self.assertEqual(capability["message"], "This model uses the JSON_CODR broker adapter for project tools.")
        self.assertNotIn("400", capability["message"])


if __name__ == "__main__":
    unittest.main()
