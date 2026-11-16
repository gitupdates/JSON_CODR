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

    def test_agent_compatibility_keeps_acceleration_and_tool_evidence_separate(self):
        from web_app.inference.compatibility import attach_agent_compatibility

        status = {"model": "qwen2.5-coder:7b", "status": "accelerated"}
        compatibility = {
            "advertised_tools": True,
            "native_tools_verified": False,
            "route": "delegated_verified",
            "effective_tool_model": "qwen3:4b",
            "available": True,
        }

        result = attach_agent_compatibility(status, compatibility)

        self.assertEqual(result["status"], "accelerated")
        self.assertEqual(result["agent_compatibility"], {
            "advertised_tools": True,
            "native_tools_verified": False,
            "tool_route": "delegated_verified",
            "effective_tool_model": "qwen3:4b",
            "tool_route_verified": True,
            "continue_verified": True,
            "aider_verified": True,
        })

    def test_agent_compatibility_does_not_claim_unverified_agent_support(self):
        from web_app.inference.compatibility import attach_agent_compatibility

        result = attach_agent_compatibility({"model": "candidate", "status": "candidate"}, {
            "advertised_tools": False,
            "native_tools_verified": False,
            "route": "unavailable",
            "effective_tool_model": None,
            "available": False,
        })

        self.assertFalse(result["agent_compatibility"]["continue_verified"])
        self.assertFalse(result["agent_compatibility"]["aider_verified"])

    def test_agent_route_does_not_claim_sessions_on_an_unavailable_profile(self):
        from web_app.inference.compatibility import attach_agent_compatibility

        result = attach_agent_compatibility({"model": "qwen3:4b", "status": "unsupported"}, {
            "advertised_tools": True,
            "native_tools_verified": True,
            "route": "native_verified",
            "effective_tool_model": "qwen3:4b",
            "available": True,
        })

        self.assertTrue(result["agent_compatibility"]["tool_route_verified"])
        self.assertFalse(result["agent_compatibility"]["continue_verified"])
        self.assertFalse(result["agent_compatibility"]["aider_verified"])


if __name__ == "__main__": unittest.main()
