import tempfile
import unittest
from pathlib import Path

from web_app.core.model_conformance import ConformanceEvidence, ModelConformanceStore


class ModelConformanceTests(unittest.TestCase):
    def evidence(self, **updates):
        values = dict(
            model="qwen2.5-coder:7b-instruct-q4_K_M", model_digest="sha256:" + "1" * 64,
            ollama_version="0.13.0", runtime_version="python-3.14",
            planner_contract_version="planner-v2", catalog_digest="sha256:" + "2" * 64,
            adapter_digests=("sha256:" + "3" * 64,), passed=True,
            evidence=("schema", "multi-step", "approval-pause"),
        )
        values.update(updates)
        return ConformanceEvidence(**values)

    def test_record_is_evidence_bound_and_invalidated_by_any_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ModelConformanceStore(Path(directory) / "conformance.sqlite")
            try:
                record = store.record(self.evidence(), classification="broker_verified")
                self.assertTrue(store.is_current(record.model, self.evidence()))
                for field, value in (
                    ("model_digest", "sha256:" + "9" * 64), ("ollama_version", "0.14.0"),
                    ("runtime_version", "python-3.15"), ("planner_contract_version", "planner-v3"),
                    ("catalog_digest", "sha256:" + "8" * 64),
                    ("adapter_digests", ("sha256:" + "7" * 64,)),
                ):
                    self.assertFalse(store.is_current(record.model, self.evidence(**{field: value})))
            finally:
                store.close()

    def test_failed_evidence_can_only_be_chat_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ModelConformanceStore(Path(directory) / "c.sqlite")
            try:
                with self.assertRaises(ValueError):
                    store.record(self.evidence(passed=False), classification="broker_verified")
                self.assertEqual(store.record(
                    self.evidence(passed=False), classification="chat_only"
                ).classification, "chat_only")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
