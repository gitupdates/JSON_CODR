import unittest


class LocalPerfQualityTests(unittest.TestCase):
    def test_json_contract_accepts_exact_shape_and_rejects_extra_fields(self):
        from web_app.localperf.quality import evaluate_quality

        self.assertTrue(evaluate_quality("lp-09", '{"status":"ok","items":[1,2]}').passed)
        self.assertFalse(evaluate_quality("lp-09", '{"status":"ok","items":[],"extra":true}').passed)

    def test_python_validators_accept_safe_code_and_reject_imports(self):
        from web_app.localperf.quality import evaluate_quality

        valid = "def clamp(value, minimum, maximum):\n    return max(minimum, min(value, maximum))"
        self.assertTrue(evaluate_quality("lp-07", valid).passed)
        self.assertFalse(evaluate_quality("lp-07", "import os\ndef clamp(*args): return os.getcwd()").passed)

    def test_sql_validator_accepts_parameterized_select_and_rejects_mutation(self):
        from web_app.localperf.quality import evaluate_quality

        self.assertTrue(evaluate_quality("lp-10", "SELECT name FROM users WHERE id = ?").passed)
        self.assertFalse(evaluate_quality("lp-10", "DROP TABLE users").passed)

    def test_unscored_prompt_is_explicitly_not_evaluated(self):
        from web_app.localperf.quality import evaluate_quality

        result = evaluate_quality("lp-01", "anything")
        self.assertIsNone(result.passed)
        self.assertEqual(result.reason, "not_scored")


if __name__ == "__main__":
    unittest.main()
