# Intel NPU first-run compatibility

JSON_CODR's reviewed Intel path uses OpenVINO GenAI 2025.4 on a separate Python 3.12 environment and the OpenVINO-published `Qwen2.5-Coder-1.5B-Instruct-int4-ov` artifact. Intel's OpenVINO NPU guidance requires 4-bit/NF4 weights for LLM export and runs the pipeline with the explicit `NPU` device. The selected model is OpenVINO IR, INT4-compressed, Apache-2.0, and compatible with OpenVINO 2025.2 or newer.

Release identity:

- Repository: `OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov`
- Commit: `3727da92d6202a996e555911c9725afd7ea54c4a`
- Reviewed download bound: 1.1 GB
- Runtime: `openvino-genai==2025.4`, `openvino-tokenizers==2025.4`
- Fallback: `qwen2.5-coder:1.5b` through Ollama

The first-run gate requires all of the following: a healthy Windows Intel NPU device, an isolated compatible provider Python, OpenVINO `NPU` enumeration, the exact commit, verified large-artifact SHA-256 values, and a bounded generation probe. Device-name detection alone is never treated as proof. Drivers are outside bootstrap authority and are never installed or changed. If any optional step fails, the model is not marked verified and the normal Ollama/CPU route remains usable.

Primary references:

- https://docs.openvino.ai/2025/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html
- https://huggingface.co/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov
