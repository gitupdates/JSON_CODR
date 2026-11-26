import json
import tempfile
import unittest
from pathlib import Path


class ModelCompatibilityLayerTests(unittest.TestCase):
    def setUp(self):
        from web_app.model_compatibility import ModelCompatibilityLayer

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.config_path = root / "model-compatibility.json"
        self.state_path = root / "compatibility-state.json"
        self.config_path.write_text(json.dumps({
            "schema_version": 1,
            "base_fallback_order": ["qwen2.5-coder:3b", "qwen2.5-coder:0.5b"],
            "models": {
                "rnj-1:8b": {
                    "alternates": ["hf.co/unsloth/rnj-1-instruct-GGUF:UD-Q4_K_XL"],
                    "prefer_alternate": True,
                    "reason": "Official artifact has incompatible SWA metadata.",
                },
            },
        }), encoding="utf-8")
        self.layer = ModelCompatibilityLayer.load(self.config_path, self.state_path)

    @staticmethod
    def live(*names):
        return {
            name: {
                "name": name,
                "digest": f"sha256:{index:064x}",
                "size": index * 100,
                "details": {"quantization_level": "Q4_K_M"},
                "capabilities": ["completion"],
            }
            for index, name in enumerate(names, start=1)
        }

    def test_rnj_prefers_reviewed_alternate_then_requested_then_base(self):
        alternate = "hf.co/unsloth/rnj-1-instruct-GGUF:UD-Q4_K_XL"
        live = self.live("rnj-1:8b", alternate, "qwen2.5-coder:3b")

        self.assertEqual(
            self.layer.candidates("rnj-1:8b", live),
            (alternate, "rnj-1:8b", "qwen2.5-coder:3b"),
        )

    def test_unknown_exact_model_uses_itself_before_reviewed_fallbacks(self):
        live = self.live("new-coder:latest", "qwen2.5-coder:3b", "qwen2.5-coder:0.5b")

        self.assertEqual(
            self.layer.candidates("new-coder:latest", live),
            ("new-coder:latest", "qwen2.5-coder:3b", "qwen2.5-coder:0.5b"),
        )

    def test_quarantined_fallback_is_skipped_but_other_reviewed_fallback_remains(self):
        live = self.live("new-coder:latest", "qwen2.5-coder:3b", "qwen2.5-coder:0.5b")
        digest = live["qwen2.5-coder:3b"]["digest"]
        self.layer.record_failure(
            "qwen2.5-coder:3b",
            digest,
            RuntimeError("GGML_ASSERT failed to load model"),
        )

        self.assertEqual(
            self.layer.candidates("new-coder:latest", live),
            ("new-coder:latest", "qwen2.5-coder:0.5b"),
        )

    def test_quarantine_is_bound_to_digest_and_does_not_poison_replacement(self):
        first = self.live("new-coder:latest")
        digest = first["new-coder:latest"]["digest"]
        self.layer.record_failure(
            "new-coder:latest",
            digest,
            RuntimeError("llama-server process has terminated"),
        )

        quarantined = self.layer.inventory(["new-coder:latest"], first)[0]
        replacement = {"new-coder:latest": {**first["new-coder:latest"], "digest": "sha256:" + "f" * 64}}
        refreshed = self.layer.inventory(["new-coder:latest"], replacement)[0]

        self.assertFalse(quarantined["runnable"])
        self.assertEqual(quarantined["compatibility_status"], "quarantined")
        self.assertIsNone(refreshed["runnable"])
        self.assertEqual(refreshed["compatibility_status"], "untested")

    def test_malformed_state_blocks_automatic_admission_but_allows_exact_manual_reprobe(self):
        self.state_path.write_text('{"models": ["not-a-mapping"]}', encoding="utf-8")
        from web_app.model_compatibility import ModelCompatibilityLayer, is_model_runnable

        layer = ModelCompatibilityLayer.load(self.config_path, self.state_path)
        live = self.live("new-coder:latest", "qwen2.5-coder:3b")

        record = layer.inventory(["new-coder:latest"], live)[0]

        self.assertTrue(record["installed"])
        self.assertEqual(record["compatibility_status"], "invalid_state")
        self.assertFalse(record["runnable"])
        self.assertFalse(is_model_runnable(record))
        self.assertEqual(layer.candidates("new-coder:latest", live), ("new-coder:latest",))

        layer.record_success("new-coder:latest", live["new-coder:latest"]["digest"], "base")

        refreshed = layer.inventory(["new-coder:latest"], live)[0]
        self.assertTrue(refreshed["runnable"])
        self.assertEqual(
            layer.candidates("new-coder:latest", live),
            ("new-coder:latest", "qwen2.5-coder:3b"),
        )

    def test_unreadable_state_blocks_automatic_admission_without_hiding_installation(self):
        self.state_path.mkdir()
        from web_app.model_compatibility import ModelCompatibilityLayer

        layer = ModelCompatibilityLayer.load(self.config_path, self.state_path)

        record = layer.inventory(["new-coder:latest"], self.live("new-coder:latest"))[0]

        self.assertTrue(record["installed"])
        self.assertFalse(record["runnable"])
        self.assertEqual(record["compatibility_status"], "invalid_state")

    def test_state_with_arbitrary_digest_fails_closed(self):
        self.state_path.write_text(json.dumps({
            "schema_version": 1,
            "models": {
                "new-coder:latest": {
                    "digest": "not-a-content-digest",
                    "status": "compatible",
                    "profile": "base",
                    "error": "",
                    "updated_at": "2026-11-25T00:00:00+00:00",
                },
            },
        }), encoding="utf-8")
        from web_app.model_compatibility import ModelCompatibilityLayer

        layer = ModelCompatibilityLayer.load(self.config_path, self.state_path)
        record = layer.inventory(["new-coder:latest"], self.live("new-coder:latest"))[0]

        self.assertEqual(record["compatibility_status"], "invalid_state")
        self.assertFalse(record["runnable"])

    def test_missing_or_arbitrary_digest_evidence_is_not_persisted(self):
        self.layer.record_success("missing:latest", "", "base")
        classification = self.layer.record_failure(
            "arbitrary:latest",
            "digest-1",
            RuntimeError("GGML_ASSERT failed to load model"),
        )

        self.assertEqual(classification, "incompatible")
        self.assertFalse(self.state_path.exists())

    def test_ollama_digest_is_normalized_before_evidence_is_persisted(self):
        uppercase = "  SHA256:" + "A" * 64 + "  "
        canonical = "sha256:" + "a" * 64

        self.layer.record_success("new-coder:latest", uppercase, "base")

        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        record = self.layer.inventory(
            ["new-coder:latest"],
            {"new-coder:latest": {"name": "new-coder:latest", "digest": canonical}},
        )[0]
        self.assertEqual(persisted["models"]["new-coder:latest"]["digest"], canonical)
        self.assertTrue(record["runnable"])

    def test_invalid_live_digest_does_not_admit_stored_compatible_evidence(self):
        valid = "sha256:" + "a" * 64
        self.layer.record_success("new-coder:latest", valid, "base")

        record = self.layer.inventory(
            ["new-coder:latest"],
            {"new-coder:latest": {"name": "new-coder:latest", "digest": "unknown"}},
        )[0]

        self.assertTrue(record["installed"])
        self.assertEqual(record["compatibility_status"], "invalid_digest")
        self.assertFalse(record["runnable"])

    def test_invalid_digest_is_never_used_as_an_automatic_fallback(self):
        requested_digest = "sha256:" + "a" * 64
        live = {
            "new-coder:latest": {
                "name": "new-coder:latest",
                "digest": requested_digest,
            },
            "qwen2.5-coder:3b": {
                "name": "qwen2.5-coder:3b",
                "digest": "untrusted",
            },
        }

        self.assertEqual(
            self.layer.candidates("new-coder:latest", live),
            ("new-coder:latest",),
        )

    def test_malformed_state_is_not_trusted_and_next_write_replaces_it_atomically(self):
        self.state_path.write_text('{"models": ["not-a-mapping"]}', encoding="utf-8")
        from web_app.model_compatibility import ModelCompatibilityLayer

        layer = ModelCompatibilityLayer.load(self.config_path, self.state_path)
        layer.record_success("new-coder:latest", "sha256:" + "a" * 64, "base")
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))

        self.assertEqual(persisted["schema_version"], 1)
        self.assertEqual(persisted["models"]["new-coder:latest"]["status"], "compatible")
        self.assertFalse(self.state_path.with_suffix(".tmp").exists())

    def test_inventory_hides_alternate_and_decorates_logical_and_discovered_models(self):
        alternate = "hf.co/unsloth/rnj-1-instruct-GGUF:UD-Q4_K_XL"
        live = self.live("rnj-1:8b", alternate, "new-coder:latest")

        inventory = self.layer.inventory(["rnj-1:8b", "missing:1b"], live)
        by_name = {item["name"]: item for item in inventory}

        self.assertEqual(set(by_name), {"rnj-1:8b", "missing:1b", "new-coder:latest"})
        self.assertTrue(by_name["rnj-1:8b"]["installed"])
        self.assertEqual(by_name["rnj-1:8b"]["effective_model"], alternate)
        self.assertEqual(by_name["rnj-1:8b"]["compatibility_status"], "untested")
        self.assertFalse(by_name["missing:1b"]["installed"])
        self.assertFalse(by_name["missing:1b"]["runnable"])
        self.assertFalse(by_name["new-coder:latest"]["configured"])

    def test_successful_base_probe_marks_matching_artifact_runnable(self):
        live = self.live("new-coder:latest")
        digest = live["new-coder:latest"]["digest"]
        self.layer.record_success("new-coder:latest", digest, "base")

        record = self.layer.inventory(["new-coder:latest"], live)[0]

        self.assertTrue(record["runnable"])
        self.assertEqual(record["compatibility_status"], "compatible")
        self.assertEqual(record["compatibility_profile"], "base")

    def test_failure_classification_distinguishes_loader_capability_and_transient_errors(self):
        self.assertEqual(
            self.layer.classify_failure(RuntimeError("GGML_ASSERT(hparams.is_swa_any()) failed")),
            "incompatible",
        )
        self.assertEqual(
            self.layer.classify_failure(RuntimeError("model does not support thinking")),
            "capability",
        )
        self.assertEqual(
            self.layer.classify_failure(RuntimeError("connection was forcibly closed")),
            "transient",
        )

    def test_unknown_output_failure_is_retained_as_nonblocking_evidence(self):
        live = self.live("new-coder:latest")
        digest = live["new-coder:latest"]["digest"]

        classification = self.layer.record_failure(
            "new-coder:latest",
            digest,
            RuntimeError("model returned malformed JSON output"),
        )

        record = self.layer.inventory(["new-coder:latest"], live)[0]
        self.assertEqual(classification, "unknown")
        self.assertEqual(record["compatibility_status"], "unknown_error")
        self.assertIsNone(record["runnable"])
        self.assertEqual(self.layer.candidates("new-coder:latest", live), ("new-coder:latest",))

    def test_legacy_failed_evidence_is_nonblocking(self):
        digest = "sha256:" + "a" * 64
        self.state_path.write_text(json.dumps({
            "schema_version": 1,
            "models": {
                "new-coder:latest": {
                    "digest": digest,
                    "status": "failed",
                    "profile": "",
                    "error": "RuntimeError: malformed output",
                    "updated_at": "2026-11-25T00:00:00+00:00",
                },
            },
        }), encoding="utf-8")
        from web_app.model_compatibility import ModelCompatibilityLayer

        layer = ModelCompatibilityLayer.load(self.config_path, self.state_path)
        live = {"new-coder:latest": {"name": "new-coder:latest", "digest": digest}}

        self.assertEqual(layer.candidates("new-coder:latest", live), ("new-coder:latest",))
        self.assertIsNone(layer.inventory(["new-coder:latest"], live)[0]["runnable"])


if __name__ == "__main__":
    unittest.main()
