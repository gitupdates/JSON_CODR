(() => {
  const terminalStatuses = new Set(["completed", "partial", "failed", "cancelled"]);
  const activeRunStorageKey = "json_codr_active_model_run";
  const elements = {};
  let activeRunId = null;
  let pollInFlight = false;
  let pollTimer = null;
  let latestRun = null;

  function bindElements() {
    for (const id of ["all-model-form", "all-model-prompt", "all-model-profile", "all-model-start", "all-model-cancel", "all-model-status", "all-model-filter", "all-model-results", "all-model-consensus", "all-model-export-json", "all-model-export-markdown", "all-model-export-csv"]) {
      elements[id] = document.getElementById(id);
    }
  }

  function sessionId() { return localStorage.getItem("json_codr_session"); }

  function setExports(runId) {
    for (const format of ["json", "markdown", "csv"]) {
      elements[`all-model-export-${format}`].href = `/api/model-runs/${encodeURIComponent(runId)}/export?format=${format}`;
    }
  }

  async function openOriginal(event) {
    event.preventDefault();
    const response = await fetch(event.currentTarget.href, { headers: { "X-JSON-CODR": "1" } });
    if (!response.ok) { elements["all-model-status"].textContent = `Original output failed (${response.status})`; return; }
    const raw = event.currentTarget.closest(".all-model-result").querySelector(".original-output-raw");
    raw.textContent = JSON.stringify(await response.json(), null, 2);
    raw.hidden = false;
    event.currentTarget.textContent = "Preserved original shown below";
  }

  function renderResult(result) {
    let row = elements["all-model-results"].querySelector(`[data-result-id="${CSS.escape(result.result_id)}"]`);
    if (!row) {
      row = document.createElement("article");
      row.className = "all-model-result";
      row.dataset.resultId = result.result_id;
      row.innerHTML = '<div class="all-model-result-head"><strong></strong><span class="meta"></span></div><h3></h3><pre></pre><a class="original-output-link">View preserved original</a><pre class="original-output-raw" hidden></pre>';
      row.querySelector(".original-output-link").addEventListener("click", openOriginal);
      elements["all-model-results"].append(row);
    }
    row.dataset.search = `${result.requested_model} ${result.status} ${result.summary} ${result.answer}`.toLowerCase();
    row.querySelector("strong").textContent = result.requested_model;
    row.querySelector("span").textContent = result.status;
    row.querySelector("h3").textContent = result.summary || "Awaiting response";
    row.querySelector("pre").textContent = result.answer || result.error_message || "";
    const original = row.querySelector(".original-output-link");
    original.href = `/api/model-runs/${encodeURIComponent(activeRunId)}/results/${encodeURIComponent(result.result_id)}/original`;
    original.dataset.model = result.requested_model;
    original.hidden = !result.original_output_id;
  }

  function render(run) {
    latestRun = run;
    elements["all-model-status"].textContent = `${run.status} · ${run.results.length} model${run.results.length === 1 ? "" : "s"}`;
    if (!elements["all-model-results"].querySelector("[data-result-id]")) elements["all-model-results"].replaceChildren();
    run.results.forEach(renderResult);
    const consensus = run.consensus;
    elements["all-model-consensus"].hidden = !consensus;
    if (consensus) elements["all-model-consensus"].textContent = `${consensus.verdict} · ${consensus.consensus_score}/10 · synthesized by ${consensus.synthesizer_model}`;
    elements["all-model-cancel"].disabled = terminalStatuses.has(run.status);
    if (terminalStatuses.has(run.status)) {
      elements["all-model-start"].disabled = false;
      return;
    }
    pollTimer = setTimeout(poll, 500);
  }

  async function poll() {
    if (!activeRunId || pollInFlight) return;
    pollInFlight = true;
    try {
      const response = await fetch(`/api/model-runs/${encodeURIComponent(activeRunId)}`);
      if (!response.ok) throw new Error(`Polling failed (${response.status})`);
      render(await response.json());
    } catch (error) {
      elements["all-model-status"].textContent = error.message;
      pollTimer = setTimeout(poll, 1500);
    } finally { pollInFlight = false; }
  }

  async function start(event) {
    event.preventDefault();
    const currentSession = sessionId();
    if (!currentSession) { elements["all-model-status"].textContent = "Create a session first."; return; }
    clearTimeout(pollTimer);
    elements["all-model-start"].disabled = true;
    elements["all-model-results"].innerHTML = '<p class="meta">Creating durable run…</p>';
    const response = await fetch("/api/model-runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: currentSession, prompt: elements["all-model-prompt"].value, profile: elements["all-model-profile"].value, request_key: crypto.randomUUID() }) });
    if (!response.ok) { elements["all-model-status"].textContent = `Run failed (${response.status})`; elements["all-model-start"].disabled = false; return; }
    const run = await response.json();
    activeRunId = run.run_id;
    localStorage.setItem(activeRunStorageKey, activeRunId);
    setExports(activeRunId);
    render(run);
  }

  async function cancel() {
    if (!activeRunId) return;
    const response = await fetch(`/api/model-runs/${encodeURIComponent(activeRunId)}/cancel`, { method: "POST" });
    if (response.ok) render(await response.json());
  }

  function filter() {
    const query = elements["all-model-filter"].value.toLowerCase();
    elements["all-model-results"].querySelectorAll("[data-result-id]").forEach((row) => { row.hidden = !row.dataset.search.includes(query); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    elements["all-model-form"].addEventListener("submit", start);
    elements["all-model-cancel"].addEventListener("click", cancel);
    elements["all-model-filter"].addEventListener("input", filter);
    activeRunId = localStorage.getItem(activeRunStorageKey);
    if (activeRunId) { setExports(activeRunId); poll(); }
  });
})();
