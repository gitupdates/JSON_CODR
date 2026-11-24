import unittest


class RepairPipelineTests(unittest.TestCase):
    def test_diagnostic_payload_is_bounded_and_redacted(self):
        from web_app.core.repair_pipeline import RepairPipeline

        pipeline = RepairPipeline()
        proposal = pipeline.diagnose(
            {
                "traceback": "Token=super-secret at C:/Users/BLACK/private.py line 7",
                "source": "x" * 20_000,
                "packages": [{"name": "safe", "version": "1.0"}],
            },
            "D:/staging",
            "coding",
        )

        self.assertNotIn("super-secret", proposal.diagnostic_payload)
        self.assertNotIn("C:/Users/BLACK", proposal.diagnostic_payload)
        self.assertLess(len(proposal.diagnostic_payload), 12_000)
        self.assertEqual(proposal.max_attempts, 3)

    def test_attempts_stop_at_three_without_claiming_repair(self):
        from web_app.core.repair_pipeline import RepairPipeline

        pipeline = RepairPipeline()
        proposal = pipeline.diagnose({"traceback": "failure", "source": "bad"}, "D:/staging", "coding")
        report = pipeline.attempt(proposal, lambda _attempt: False)

        self.assertFalse(report.verified)
        self.assertEqual(report.attempts, 3)
        self.assertEqual(report.status, "exhausted")


if __name__ == "__main__":
    unittest.main()
