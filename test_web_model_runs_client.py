import json
import subprocess
import unittest
from pathlib import Path


class ModelRunsClientTests(unittest.TestCase):
    def run_client(self, harness):
        runtime = Path("web/model_runs.js").read_text(encoding="utf-8")
        completed = subprocess.run(
            ["node", "-e", harness],
            env={"MODEL_RUNS_SOURCE": runtime},
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_start_uses_page_live_session_and_mutation_headers(self):
        harness = r"""
const vm = require("vm");
const callbacks = {};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, disabled: false, hidden: false, href: "", textContent: "", value: "",
    addEventListener(name, callback) { callbacks[`${id}:${name}`] = callback; },
    querySelector() { return null; }, querySelectorAll() { return []; }, replaceChildren() {},
  });
  return elements.get(id);
}
element("all-model-prompt").value = "Run this";
element("all-model-profile").value = "base";
element("all-model-parallelism").value = "2";
const requests = [];
const sessionReads = [];
const context = {
  document: { addEventListener(name, callback) { callbacks[name] = callback; }, getElementById: element },
  localStorage: {
    getItem(key) { if (key === "json_codr_session") sessionReads.push(key); return null; },
    setItem() {}, removeItem() {},
  },
  fetch: async (url, options = {}) => {
    requests.push({url, options});
    return {ok: true, status: 200, json: async () => ({run_id: "run-1", status: "completed", results: [], consensus: null})};
  },
  setTimeout() { return 1; }, clearTimeout() {}, CSS: { escape(value) { return value; } },
  crypto: { randomUUID() { return "request-1"; } },
  window: {
    JSONCodrLiveSession: { ensure: async () => "page-session" },
    JSONCodrHttpIdentity: { mutationHeaders(extra) { return {...extra, "X-CSRF-Token": "csrf-1"}; } },
  },
};
vm.runInNewContext(process.env.MODEL_RUNS_SOURCE, context);
callbacks.DOMContentLoaded();
(async () => {
  await callbacks["all-model-form:submit"]({preventDefault() {}});
  process.stdout.write(JSON.stringify({request: requests[0] || null, sessionReads, status: element("all-model-status").textContent}));
})();
"""

        result = self.run_client(harness)

        self.assertEqual(result["sessionReads"], [])
        self.assertIsNotNone(result["request"])
        self.assertEqual(result["request"]["url"], "/api/model-runs")
        self.assertEqual(result["request"]["options"]["headers"], {
            "Content-Type": "application/json", "X-CSRF-Token": "csrf-1",
        })
        self.assertEqual(json.loads(result["request"]["options"]["body"])["session_id"], "page-session")

    def test_cancel_uses_mutation_headers_and_restores_controls_with_forbidden_detail(self):
        harness = r"""
const vm = require("vm");
const callbacks = {};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, disabled: false, hidden: false, href: "", textContent: "", value: "",
    addEventListener(name, callback) { callbacks[`${id}:${name}`] = callback; },
    querySelector() { return null; }, querySelectorAll() { return []; }, replaceChildren() {},
  });
  return elements.get(id);
}
element("all-model-prompt").value = "Run this";
element("all-model-profile").value = "base";
element("all-model-parallelism").value = "2";
const requests = [];
const sessionReads = [];
let count = 0;
const context = {
  document: { addEventListener(name, callback) { callbacks[name] = callback; }, getElementById: element },
  localStorage: {
    getItem(key) { if (key === "json_codr_session") sessionReads.push(key); return null; },
    setItem() {}, removeItem() {},
  },
  fetch: async (url, options = {}) => {
    requests.push({url, options}); count += 1;
    return count === 1
      ? {ok: true, status: 200, json: async () => ({run_id: "run-1", status: "running", results: [], consensus: null})}
      : {ok: false, status: 403, json: async () => ({detail: "Access denied"})};
  },
  setTimeout() { return 1; }, clearTimeout() {}, CSS: { escape(value) { return value; } },
  crypto: { randomUUID() { return "request-1"; } },
  window: {
    JSONCodrLiveSession: { ensure: async () => "page-session" },
    JSONCodrHttpIdentity: { mutationHeaders(extra) { return {...extra, "X-CSRF-Token": "csrf-1"}; } },
  },
};
vm.runInNewContext(process.env.MODEL_RUNS_SOURCE, context);
callbacks.DOMContentLoaded();
(async () => {
  await callbacks["all-model-form:submit"]({preventDefault() {}});
  await callbacks["all-model-cancel:click"]();
  process.stdout.write(JSON.stringify({request: requests[1] || null, sessionReads, status: element("all-model-status").textContent, startDisabled: element("all-model-start").disabled, cancelDisabled: element("all-model-cancel").disabled}));
})();
"""

        result = self.run_client(harness)

        self.assertEqual(result["sessionReads"], [])
        self.assertIsNotNone(result["request"])
        self.assertEqual(result["request"]["url"], "/api/model-runs/run-1/cancel")
        self.assertEqual(result["request"]["options"]["headers"], {"X-CSRF-Token": "csrf-1"})
        self.assertEqual(result["status"], "Access denied")
        self.assertFalse(result["startDisabled"])
        self.assertFalse(result["cancelDisabled"])

    def test_missing_saved_run_is_cleared_without_retrying(self):
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
        result = self.run_client(harness)

        self.assertEqual(result["status"], "Saved run is no longer available. Start a new run.")
        self.assertIsNone(result["savedRun"])
        self.assertEqual(result["timerCount"], 0)
        self.assertFalse(result["startDisabled"])
        self.assertTrue(result["cancelDisabled"])


if __name__ == "__main__":
    unittest.main()
