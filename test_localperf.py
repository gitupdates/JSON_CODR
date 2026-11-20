import json
import unittest

from pydantic import ValidationError


class LocalPerfContractTests(unittest.TestCase):
    def test_core_workload_is_versioned_and_has_twelve_stable_prompts(self):
        from web_app.localperf.workload import CORE_WORKLOAD, WORKLOAD_NAME, WORKLOAD_VERSION, workload_hash

        self.assertEqual(WORKLOAD_NAME, "LocalPerf-Core-v1")
        self.assertEqual(WORKLOAD_VERSION, "1.0")
        self.assertEqual(len(CORE_WORKLOAD), 12)
        self.assertEqual([item.id for item in CORE_WORKLOAD], [f"lp-{index:02d}" for index in range(1, 13)])
        self.assertEqual({item.id for item in CORE_WORKLOAD if item.quality_scored}, {"lp-07", "lp-08", "lp-09", "lp-10"})
        self.assertEqual(workload_hash(), workload_hash())
        self.assertEqual(len(workload_hash()), 64)

    def test_sample_requires_all_normative_metrics(self):
        from web_app.localperf.models import SampleRecord

        with self.assertRaises(ValidationError):
            SampleRecord.model_validate({
                "prompt_id": "lp-01", "repetition": 1, "success": True,
                "generation_tokens_per_second": 1.0, "ttft_ms": 5.0,
            })

    def test_exported_schema_uses_localperf_schema_version(self):
        from web_app.localperf.models import LOCALPERF_SCHEMA_VERSION, LocalPerfRun

        schema = LocalPerfRun.model_json_schema()
        self.assertEqual(LOCALPERF_SCHEMA_VERSION, "0.3.0-localperf")
        self.assertIn("samples", schema["required"])
        self.assertIn("configuration", schema["required"])

    def test_configuration_hash_changes_with_execution_identity(self):
        from web_app.localperf.fingerprint import configuration_hash

        base = {"model": "qwen", "backend": "cpu", "profile": "automatic", "hardware": {"cpu": "x"}, "software": {"app": "1"}}
        self.assertEqual(configuration_hash(base), configuration_hash(dict(base)))
        changed = json.loads(json.dumps(base))
        changed["backend"] = "directml"
        self.assertNotEqual(configuration_hash(base), configuration_hash(changed))


if __name__ == "__main__":
    unittest.main()
