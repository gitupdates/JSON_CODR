import unittest

from pydantic import ValidationError


class InferenceProtocolTests(unittest.TestCase):
    def test_request_preserves_ordered_typed_messages_and_controls(self):
        from web_app.inference.protocol import (
            CancellationMetadata,
            ContentPart,
            InferenceMessage,
            InferenceRequest,
            ResponseFormat,
            ToolDefinition,
        )

        request = InferenceRequest(
            request_id="req-1",
            model="qwen3:4b",
            messages=(
                InferenceMessage(role="system", content=(ContentPart(type="text", text="Be exact."),)),
                InferenceMessage(
                    role="user",
                    content=(
                        ContentPart(type="text", text="Inspect this image."),
                        ContentPart(type="image", image_url="attachment://diagram-1", mime_type="image/png"),
                    ),
                ),
                InferenceMessage(
                    role="assistant",
                    content=(
                        ContentPart(
                            type="tool_call",
                            tool_call_id="call-1",
                            tool_name="read_file",
                            arguments={"path": "README.md"},
                        ),
                    ),
                ),
                InferenceMessage(
                    role="tool",
                    content=(ContentPart(type="tool_result", tool_call_id="call-1", result="contents"),),
                ),
            ),
            tools=(
                ToolDefinition(
                    name="read_file",
                    description="Read a project file",
                    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                ),
            ),
            tool_choice="auto",
            temperature=0.2,
            top_p=0.9,
            max_output_tokens=512,
            stop=("END",),
            seed=7,
            response_format=ResponseFormat(type="json_schema", json_schema={"type": "object"}),
            cancellation=CancellationMetadata(token="cancel-1", disconnect_cancels=False),
        )

        self.assertEqual([message.role for message in request.messages], ["system", "user", "assistant", "tool"])
        self.assertEqual([part.type for part in request.messages[1].content], ["text", "image"])
        self.assertEqual(request.messages[2].content[0].arguments, {"path": "README.md"})
        self.assertEqual(request.tools[0].name, "read_file")
        self.assertEqual(request.tool_choice, "auto")
        self.assertEqual(request.response_format.type, "json_schema")
        self.assertFalse(request.cancellation.disconnect_cancels)

    def test_contracts_are_frozen_and_reject_unknown_fields(self):
        from web_app.inference.protocol import ContentPart, InferenceMessage, InferenceRequest

        request = InferenceRequest(
            model="qwen3:4b",
            messages=(InferenceMessage(role="user", content=(ContentPart(type="text", text="Hello"),)),),
        )

        with self.assertRaises(ValidationError):
            request.model = "other"
        with self.assertRaises(ValidationError):
            InferenceRequest(
                model="qwen3:4b",
                messages=request.messages,
                unknown_control=True,
            )

    def test_event_records_provenance_usage_finish_and_cancellation(self):
        from web_app.inference.protocol import (
            InferenceEvent,
            InferenceFinishReason,
            InferenceUsage,
        )

        event = InferenceEvent(
            type="completed",
            requested_model="qwen2.5-coder:7b",
            effective_model="qwen3:4b",
            route="ollama_gpu",
            usage=InferenceUsage(input_tokens=11, output_tokens=5, total_tokens=16),
            finish_reason=InferenceFinishReason.stop,
            cancellation_token="cancel-1",
        )

        self.assertEqual(event.requested_model, "qwen2.5-coder:7b")
        self.assertEqual(event.effective_model, "qwen3:4b")
        self.assertEqual(event.usage.total_tokens, 16)
        self.assertEqual(event.finish_reason, InferenceFinishReason.stop)
        self.assertEqual(event.cancellation_token, "cancel-1")


if __name__ == "__main__":
    unittest.main()
