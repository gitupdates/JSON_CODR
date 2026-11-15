import unittest

from web_app.inference.contracts import OptimizedModelRecord, ProviderKind


class ModelCompatibilityTests(unittest.TestCase):
    def test_ollama_gpu_requires_positive_vram_evidence(self):
        from web_app.inference.compatibility import ollama_model_status

        self.assertEqual(ollama_model_status("qwen", "ollama_gpu", [], True)["status"], "runnable")
        active = [{"name":"qwen", "size_vram":100, "processor":"100% GPU"}]
        self.assertEqual(ollama_model_status("qwen", "ollama_gpu", active, True)["status"], "accelerated")
        self.assertEqual(ollama_model_status("qwen", "ollama_gpu", active, True)["evidence"]["vram_bytes"], 100)

    def test_optimized_model_states_distinguish_candidate_installed_and_accelerated(self):
        from web_app.inference.compatibility import optimized_model_status

        model = OptimizedModelRecord(id="openvino/org/model", provider=ProviderKind.openvino,
            repository="org/model", source_url="https://huggingface.co/org/model", revision="abc",
            license="apache-2.0", device="NPU", format="openvino_ir", requirements=())
        self.assertEqual(optimized_model_status(model, False, False, False)["status"], "candidate")
        self.assertEqual(optimized_model_status(model, True, True, False)["status"], "runnable")
        self.assertEqual(optimized_model_status(model, True, True, True)["status"], "accelerated")


if __name__ == "__main__": unittest.main()
