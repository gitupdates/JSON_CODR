import unittest

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import OptimizedModelRecord, ProviderKind


class InferenceContractTests(unittest.TestCase):
    def test_qualified_model_ids_do_not_collide_with_ollama_names(self):
        catalog = OptimizedModelCatalog()

        for model in catalog.list():
            self.assertTrue(model.id.startswith(f"{model.provider.value}/"))
            self.assertNotEqual(model.id, model.ollama_fallback)

    def test_catalog_exposes_initial_vendor_models_with_license_and_fallback(self):
        catalog = OptimizedModelCatalog()
        models = {model.id: model for model in catalog.list()}

        openvino = models["openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov"]
        self.assertEqual(openvino.provider, ProviderKind.openvino)
        self.assertEqual(openvino.device, "NPU")
        self.assertEqual(openvino.format, "openvino_ir")
        self.assertEqual(openvino.license, "apache-2.0")
        self.assertTrue(openvino.source_url.startswith("https://huggingface.co/"))
        self.assertTrue(openvino.revision)
        self.assertTrue(openvino.requirements)
        self.assertLessEqual(openvino.maximum_download_bytes, 1_100_000_000)
        self.assertGreaterEqual(len(openvino.artifacts), 4)
        self.assertTrue(all(len(artifact.sha256) == 64 for artifact in openvino.artifacts))
        self.assertEqual(openvino.ollama_fallback, "qwen2.5-coder:1.5b")

        amd = models["ryzen_ai/amd/Qwen2.5-Coder-0.5B-Instruct_rai_1.8.0_m1.0_npu"]
        self.assertEqual(amd.provider, ProviderKind.ryzen_ai)
        self.assertEqual(amd.device, "NPU")
        self.assertEqual(amd.format, "onnx_genai")
        self.assertTrue(amd.source_url.startswith("https://huggingface.co/"))
        self.assertTrue(amd.requirements)
        self.assertEqual(amd.ollama_fallback, "qwen2.5-coder:0.5b")

    def test_catalog_rejects_duplicate_or_unqualified_ids(self):
        valid = OptimizedModelCatalog().list()[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            OptimizedModelCatalog([valid, valid])

        invalid = valid.model_copy(update={"id": "Qwen2.5-Coder"})
        with self.assertRaisesRegex(ValueError, "qualified"):
            OptimizedModelCatalog([invalid])


if __name__ == "__main__":
    unittest.main()
