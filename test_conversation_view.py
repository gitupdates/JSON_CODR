import json
import subprocess
import unittest
from pathlib import Path


class ConversationViewTests(unittest.TestCase):
    def run_node(self, body: str):
        script = f"""
const ConversationView = require('./web/conversation_view.js');
{body}
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).parent,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_applies_stream_deltas_once_and_keeps_reasoning_separate(self):
        result = self.run_node("""
const view = new ConversationView();
view.beginTask('task-1', { requestedModel: 'requested', parentMessageId: 'a'.repeat(32) });
const record = { task_id: 'task-1', status: 'running', events: [
  { sequence: 1, event_type: 'inference.reasoning.delta', payload: { text: 'Check evidence', provenance: 'native_provider' } },
  { sequence: 2, event_type: 'inference.content.delta', payload: { text: 'Hello ' } },
  { sequence: 2, event_type: 'inference.content.delta', payload: { text: 'Hello ' } },
  { sequence: 3, event_type: 'inference.content.delta', payload: { text: 'world' } },
]};
view.apply(record); view.apply(record);
console.log(JSON.stringify(view.snapshot()));
""")
        message = result[0]
        self.assertEqual(message["content"], "Hello world")
        self.assertEqual(len(message["reasoning"]["entries"]), 1)
        self.assertEqual(message["reasoning"]["entries"][0]["provenance"], "native_provider")

    def test_restores_legacy_history_and_marks_partial_failure(self):
        result = self.run_node("""
const view = new ConversationView();
view.restoreMessages([{ role: 'assistant', content: 'Legacy answer' }]);
view.beginTask('task-failed', { requestedModel: 'model' });
view.apply({ task_id: 'task-failed', status: 'failed', events: [
  { sequence: 1, event_type: 'inference.content.delta', payload: { text: 'Partial' } },
  { sequence: 2, event_type: 'task.failed', payload: { reason: 'Provider disconnected' } },
]});
console.log(JSON.stringify(view.snapshot()));
""")
        self.assertEqual(result[0]["status"], "completed")
        self.assertEqual(result[1]["status"], "incomplete")
        self.assertIn("Provider disconnected", result[1]["error"])

    def test_renderer_uses_safe_text_and_bounded_reference_routes(self):
        source = Path("web/conversation_view.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", source)
        self.assertIn("textContent", source)
        self.assertIn("/references/", source)
        self.assertNotIn("reference.target", source)

    def test_persist_uses_identity_mutation_headers(self):
        result = self.run_node("""
global.JSONCodrHttpIdentity = {
  mutationHeaders(headers) { return { ...headers, 'X-CSRF-Token': 'csrf-test' }; },
};
let captured;
const view = new ConversationView({ fetchImpl: async (url, options) => {
  captured = { url, options };
  return { ok: true };
} });
view.sessionId = 'session-1';
view.appendUser('Hello').then(() => console.log(JSON.stringify(captured)));
""")
        self.assertEqual(result["url"], "/api/sessions/session-1/conversation")
        self.assertEqual(result["options"]["headers"]["Content-Type"], "application/json")
        self.assertEqual(result["options"]["headers"]["X-CSRF-Token"], "csrf-test")


if __name__ == "__main__":
    unittest.main()
