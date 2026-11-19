import json
import subprocess
import unittest
from pathlib import Path


class ModelRunsClientTests(unittest.TestCase):
    def test_missing_saved_run_is_cleared_without_retrying(self):
        runtime = Path("web/model_runs.js").read_text(encoding="utf-8")
        harness = r"""
const vm = require("vm");
const callbacks = {};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, disabled: false, hidden: false, href: "", textContent: "", value: "",
    addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    replaceChildren() {},
  });
  return elements.get(id);
}
const storage = new Map([
  ["json_codr_active_model_run", "missing-run"],
  ["json_codr_session", "session-1"],
]);
const timers = [];
const context = {
  document: {
    addEventListener(name, callback) { callbacks[name] = callback; },
    getElementById(id) { return element(id); },
  },
  localStorage: {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
    removeItem(key) { storage.delete(key); },
  },
  fetch: async () => ({ ok: false, status: 404 }),
  setTimeout(callback, delay) { timers.push({ callback, delay }); return timers.length; },
  clearTimeout() {},
  CSS: { escape(value) { return value; } },
  crypto: { randomUUID() { return "request-1"; } },
  console,
};
vm.runInNewContext(process.env.MODEL_RUNS_SOURCE, context);
callbacks.DOMContentLoaded();
setImmediate(() => {
  process.stdout.write(JSON.stringify({
    status: element("all-model-status").textContent,
    savedRun: storage.get("json_codr_active_model_run") || null,
    timerCount: timers.length,
    startDisabled: element("all-model-start").disabled,
    cancelDisabled: element("all-model-cancel").disabled,
  }));
});
"""
        completed = subprocess.run(
            ["node", "-e", harness],
            env={"MODEL_RUNS_SOURCE": runtime},
            text=True,
            capture_output=True,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["status"], "Saved run is no longer available. Start a new run.")
        self.assertIsNone(result["savedRun"])
        self.assertEqual(result["timerCount"], 0)
        self.assertFalse(result["startDisabled"])
        self.assertTrue(result["cancelDisabled"])


if __name__ == "__main__":
    unittest.main()
