const elements = {
  form: document.querySelector("#chat-form"),
  health: document.querySelector("#health-status"),
  model: document.querySelector("#model-select"),
  modelCount: document.querySelector("#model-count"),
  modelDetail: document.querySelector("#model-detail"),
  prompt: document.querySelector("#prompt-input"),
  submit: document.querySelector("#submit-button"),
  cancel: document.querySelector("#cancel-button"),
  requestStatus: document.querySelector("#request-status"),
  responseModel: document.querySelector("#response-model"),
  empty: document.querySelector("#empty-state"),
  result: document.querySelector("#result-state"),
  summary: document.querySelector("#summary-output"),
  content: document.querySelector("#content-output"),
  error: document.querySelector("#error-output"),
  contextToggle: document.querySelector("#context-toggle"),
  contextPanel: document.querySelector("#context-panel"),
  contextCount: document.querySelector("#context-count"),
  attachmentInput: document.querySelector("#attachment-input"),
  pasteTextButton: document.querySelector("#paste-text-button"),
  attachmentList: document.querySelector("#attachment-list"),
  attachmentPreview: document.querySelector("#attachment-preview"),
};

let models = [];
let activeRequest = null;
let sessionId = localStorage.getItem("json_codr_session");

async function ensureSession() {
  if (sessionId && (await fetch(`/api/sessions/${sessionId}`)).ok) return sessionId;
  const session = await fetch("/api/sessions", { method: "POST" }).then((response) => response.json());
  sessionId = session.id;
  localStorage.setItem("json_codr_session", sessionId);
  return sessionId;
}

async function loadAttachments() {
  await ensureSession();
  const attachments = await fetch(`/api/sessions/${sessionId}/attachments`).then((response) => response.json());
  elements.contextCount.textContent = `${attachments.length} item${attachments.length === 1 ? "" : "s"}`;
  elements.attachmentList.replaceChildren();
  if (!attachments.length) elements.attachmentList.innerHTML = '<p class="meta">No context attached.</p>';
  for (const item of attachments) {
    const row = document.createElement("div");
    row.className = "attachment-row";
    const label = document.createElement("button");
    label.type = "button";
    label.textContent = `${item.included ? "●" : "○"} ${item.display_name} · ${item.extraction_state}`;
    label.addEventListener("click", async () => {
      const preview = await fetch(`/api/sessions/${sessionId}/attachments/${item.id}/preview`).then((response) => response.json());
      elements.attachmentPreview.textContent = preview.text;
      elements.attachmentPreview.hidden = false;
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", async () => {
      await fetch(`/api/sessions/${sessionId}/attachments/${item.id}`, { method: "DELETE" });
      await loadAttachments();
    });
    const download = document.createElement("a");
    download.textContent = "Download";
    download.href = `/api/sessions/${sessionId}/attachments/${item.id}/original`;
    download.className = "attachment-action";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", async () => {
      const response = await fetch(`/api/sessions/${sessionId}/attachments/${item.id}/retry`, { method: "POST" });
      if (!response.ok) showError((await response.json()).detail || "Extraction retry failed");
      await loadAttachments();
    });
    const actions = document.createElement("div");
    actions.className = "attachment-actions";
    actions.append(download, retry, remove);
    row.append(label, actions);
    elements.attachmentList.append(row);
  }
}

async function uploadFiles(files) {
  await ensureSession();
  for (const file of files) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`/api/sessions/${sessionId}/attachments`, { method: "POST", body });
    if (!response.ok) showError((await response.json()).detail || `Unable to import ${file.name}`);
  }
  await loadAttachments();
}

function selectedModel() {
  return models.find((model) => model.name === elements.model.value);
}

function updateModelDetail() {
  const model = selectedModel();
  if (!model) return;
  const size = model.size ? `${(model.size / 1e9).toFixed(1)} GB` : "size unavailable";
  const context = model.context_length ? `${model.context_length.toLocaleString()} ctx` : "context unavailable";
  const capabilities = model.capabilities.length ? model.capabilities.join(" · ") : "completion";
  elements.modelDetail.textContent = `${model.quantization || "quantization unknown"} · ${size} · ${context} · ${capabilities}`;
}

async function loadApplication() {
  try {
    const [healthResponse, modelsResponse] = await Promise.all([fetch("/api/health"), fetch("/api/models")]);
    const health = await healthResponse.json();
    const payload = await modelsResponse.json();
    if (!modelsResponse.ok) throw new Error(payload.detail || "Unable to load models");
    models = payload.models;
    elements.health.className = `health ${health.ollama ? "ready" : "error"}`;
    elements.health.lastElementChild.textContent = health.ollama ? "Ollama ready" : "Ollama offline";
    elements.model.innerHTML = "";
    for (const model of models) {
      const option = document.createElement("option");
      option.value = model.name;
      option.textContent = `${model.name}${model.installed ? "" : " — not installed"}`;
      option.disabled = !model.installed;
      elements.model.append(option);
    }
    const installed = models.filter((model) => model.installed).length;
    elements.modelCount.textContent = `${installed} of ${models.length} installed`;
    elements.model.disabled = installed === 0;
    elements.submit.disabled = installed === 0;
    updateModelDetail();
  } catch (error) {
    elements.health.className = "health error";
    elements.health.lastElementChild.textContent = "Service unavailable";
    elements.modelDetail.textContent = error.message;
  }
}

function setPending(pending) {
  elements.submit.disabled = pending;
  elements.model.disabled = pending;
  elements.prompt.disabled = pending;
  elements.cancel.hidden = !pending;
  elements.requestStatus.textContent = pending ? "Model is working…" : "";
}

function showError(message) {
  elements.empty.hidden = true;
  elements.result.hidden = true;
  elements.error.hidden = false;
  elements.error.textContent = message;
}

async function submitPrompt(event) {
  event.preventDefault();
  const prompt = elements.prompt.value.trim();
  if (!prompt) {
    showError("Enter a prompt before running the model.");
    elements.prompt.focus();
    return;
  }
  activeRequest = new AbortController();
  setPending(true);
  elements.error.hidden = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: elements.model.value, prompt, session_id: sessionId }),
      signal: activeRequest.signal,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "The model request failed");
    elements.empty.hidden = true;
    elements.error.hidden = true;
    elements.result.hidden = false;
    elements.responseModel.textContent = payload.model;
    elements.summary.textContent = payload.summary;
    elements.content.textContent = payload.content;
  } catch (error) {
    showError(error.name === "AbortError" ? "Request cancelled." : error.message);
  } finally {
    activeRequest = null;
    setPending(false);
  }
}

elements.form.addEventListener("submit", submitPrompt);
elements.cancel.addEventListener("click", () => activeRequest?.abort());
elements.model.addEventListener("change", updateModelDetail);
elements.prompt.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") elements.form.requestSubmit();
});
elements.contextToggle.addEventListener("click", () => {
  elements.contextPanel.hidden = !elements.contextPanel.hidden;
  elements.contextToggle.setAttribute("aria-expanded", String(!elements.contextPanel.hidden));
  localStorage.setItem("json_codr_context_open", String(!elements.contextPanel.hidden));
});
elements.attachmentInput.addEventListener("change", () => uploadFiles(elements.attachmentInput.files));
elements.pasteTextButton.addEventListener("click", async () => {
  await ensureSession();
  const text = await navigator.clipboard.readText();
  if (!text.trim()) return;
  await fetch(`/api/sessions/${sessionId}/clipboard-text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  await loadAttachments();
});
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.altKey && event.key.toLowerCase() === "b") {
    event.preventDefault();
    elements.contextToggle.click();
  }
});

loadApplication();
loadAttachments().catch((error) => showError(error.message));
