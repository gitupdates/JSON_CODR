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
  artifactOutput: document.querySelector("#artifact-output"),
  error: document.querySelector("#error-output"),
  contextToggle: document.querySelector("#context-toggle"),
  contextPanel: document.querySelector("#context-panel"),
  contextCount: document.querySelector("#context-count"),
  attachmentInput: document.querySelector("#attachment-input"),
  pasteTextButton: document.querySelector("#paste-text-button"),
  attachmentList: document.querySelector("#attachment-list"),
  attachmentPreview: document.querySelector("#attachment-preview"),
  exportArchive: document.querySelector("#export-archive"),
  dependencyList: document.querySelector("#dependency-list"),
  scanDependencies: document.querySelector("#scan-dependencies"),
  skillList: document.querySelector("#skill-list"),
  skillPreview: document.querySelector("#skill-preview"),
  skillInstall: document.querySelector("#skill-install"),
  skillDeduplicate: document.querySelector("#skill-deduplicate"),
  skillEditor: document.querySelector("#skill-editor"),
  skillEnabled: document.querySelector("#skill-enabled"),
  skillSave: document.querySelector("#skill-save"),
  skillRemovePack: document.querySelector("#skill-remove-pack"),
  skillConversionStatus: document.querySelector("#skill-conversion-status"),
  terminalToggle: document.querySelector("#terminal-toggle"),
  terminalPanel: document.querySelector("#terminal-panel"),
  terminalOutput: document.querySelector("#terminal-output"),
  terminalInput: document.querySelector("#terminal-input"),
  terminalRun: document.querySelector("#terminal-run"),
  terminalStop: document.querySelector("#terminal-stop"),
  terminalStatus: document.querySelector("#terminal-status"),
};

let models = [];
let activeRequest = null;
let sessionId = localStorage.getItem("json_codr_session");
let terminalId = null;
let terminalSocket = null;
let skillAttachmentId = null;
let editingSkill = null;
let skillLoadGeneration = 0;

function appendTerminalOutput(text) {
  elements.terminalOutput.textContent += text;
  elements.terminalOutput.scrollTop = elements.terminalOutput.scrollHeight;
}

async function ensureTerminal() {
  if (terminalSocket?.readyState === WebSocket.OPEN) return;
  elements.terminalStatus.textContent = "Starting...";
  const response = await fetch("/api/terminals", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-JSON-CODR": "1" },
    body: JSON.stringify({ shell: "powershell" }),
  });
  if (!response.ok) throw new Error((await response.json()).detail || "Unable to start terminal");
  const terminal = await response.json();
  terminalId = terminal.id;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  terminalSocket = new WebSocket(`${protocol}//${location.host}/ws/terminals/${terminalId}`);
  terminalSocket.addEventListener("open", () => {
    elements.terminalStatus.textContent = `PowerShell · PID ${terminal.pid}`;
    appendTerminalOutput(`PowerShell ready in ${terminal.cwd}\n`);
  });
  terminalSocket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "output") appendTerminalOutput(message.data);
    if (message.type === "exit") elements.terminalStatus.textContent = "Stopped";
  });
  terminalSocket.addEventListener("close", () => { elements.terminalStatus.textContent = "Disconnected"; });
}

async function runTerminalCommand() {
  const command = elements.terminalInput.value;
  if (!command.trim()) return;
  await ensureTerminal();
  if (terminalSocket.readyState !== WebSocket.OPEN) {
    await new Promise((resolve) => terminalSocket.addEventListener("open", resolve, { once: true }));
  }
  terminalSocket.send(JSON.stringify({ type: "input", data: `${command}\r\n` }));
  elements.terminalInput.value = "";
}

async function ensureSession() {
  if (sessionId && (await fetch(`/api/sessions/${sessionId}`)).ok) return sessionId;
  const session = await fetch("/api/sessions", { method: "POST" }).then((response) => response.json());
  sessionId = session.id;
  localStorage.setItem("json_codr_session", sessionId);
  return sessionId;
}

async function loadAttachments() {
  await ensureSession();
  elements.exportArchive.href = `/api/sessions/${sessionId}/archive.zip`;
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
    const reviewSkills = document.createElement("button");
    reviewSkills.type = "button";
    reviewSkills.textContent = "Review as skills";
    reviewSkills.addEventListener("click", () => {
      skillAttachmentId = item.id;
      elements.skillPreview.disabled = false;
      elements.skillInstall.disabled = true;
      elements.skillConversionStatus.textContent = `Ready to preview ${item.display_name}`;
    });
    actions.append(download, retry, reviewSkills, remove);
    row.append(label, actions);
    elements.attachmentList.append(row);
  }
  await loadDependencies();
  await loadSkills();
}

async function saveSkillSelection() {
  const selected = [...elements.skillList.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
  const response = await fetch(`/api/sessions/${sessionId}/skills`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selected }),
  });
  if (!response.ok) throw new Error((await response.json()).detail || "Unable to update skill selection");
}

async function loadSkills() {
  const generation = ++skillLoadGeneration;
  await ensureSession();
  const [packs, session] = await Promise.all([
    fetch("/api/skills").then((response) => response.json()),
    fetch(`/api/sessions/${sessionId}`).then((response) => response.json()),
  ]);
  if (generation !== skillLoadGeneration) return;
  const selected = new Set(session.selected_skill_ids || []);
  const content = document.createDocumentFragment();
  if (!packs.length) {
    const empty = document.createElement("p");
    empty.className = "meta";
    empty.textContent = "No skills installed.";
    content.append(empty);
  }
  for (const pack of packs) {
    const group = document.createElement("section");
    group.className = "skill-pack";
    const heading = document.createElement("strong");
    heading.textContent = `${pack.name} · ${pack.source_format}`;
    group.append(heading);
    for (const skill of pack.skills) {
      const row = document.createElement("div");
      row.className = "skill-row";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = `${pack.id}:${skill.id}`;
      checkbox.checked = selected.has(checkbox.value);
      checkbox.disabled = !skill.enabled;
      checkbox.addEventListener("change", () => saveSkillSelection().catch((error) => showError(error.message)));
      label.append(checkbox, document.createTextNode(` ${skill.name}${skill.enabled ? "" : " · disabled"}`));
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => {
        editingSkill = { packId: pack.id, skillId: skill.id, enabled: skill.enabled };
        elements.skillEditor.value = skill.content;
        elements.skillEditor.disabled = false;
        elements.skillEnabled.checked = skill.enabled;
        elements.skillEnabled.disabled = false;
        elements.skillSave.disabled = false;
        elements.skillRemovePack.disabled = false;
      });
      row.append(label, edit);
      group.append(row);
    }
    content.append(group);
  }
  if (generation !== skillLoadGeneration) return;
  elements.skillList.replaceChildren(content);
}

async function loadDependencies() {
  await ensureSession();
  const response = await fetch(`/api/sessions/${sessionId}/dependencies`);
  if (!response.ok) throw new Error("Unable to scan dependency manifests");
  const suggestions = await response.json();
  elements.dependencyList.replaceChildren();
  if (!suggestions.length) {
    elements.dependencyList.innerHTML = '<p class="meta">No supported dependency manifests detected.</p>';
    return;
  }
  for (const suggestion of suggestions) {
    const row = document.createElement("div");
    row.className = "dependency-row";
    const details = document.createElement("div");
    const source = document.createElement("strong");
    source.textContent = `${suggestion.source} · ${suggestion.ecosystem}`;
    const command = document.createElement("code");
    command.textContent = suggestion.command;
    details.append(source, command);
    const send = document.createElement("button");
    send.type = "button";
    send.className = "secondary";
    send.textContent = "Send to CLI";
    send.addEventListener("click", async () => {
      if (elements.terminalPanel.hidden) elements.terminalToggle.click();
      elements.terminalInput.value = suggestion.command;
      elements.terminalInput.focus();
      elements.terminalStatus.textContent = "Install command ready · review and press Run";
    });
    row.append(details, send);
    elements.dependencyList.append(row);
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
    elements.artifactOutput.hidden = !payload.artifact;
    if (payload.artifact) {
      elements.artifactOutput.href = payload.artifact.url;
      elements.artifactOutput.textContent = `Download ${payload.artifact.filename}`;
    }
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
elements.scanDependencies.addEventListener("click", () => loadDependencies().catch((error) => showError(error.message)));
elements.skillPreview.addEventListener("click", async () => {
  const response = await fetch(`/api/sessions/${sessionId}/attachments/${skillAttachmentId}/skill-preview`, { method: "POST" });
  const payload = await response.json();
  if (!response.ok) return showError(payload.detail || "Skill conversion preview failed");
  elements.skillConversionStatus.textContent = `${payload.source_format} pack · ${payload.skills.length} skills · review complete`;
  elements.skillEditor.value = payload.skills.map((skill) => `# ${skill.name}\n${skill.content}`).join("\n\n---\n\n");
  elements.skillEditor.disabled = false;
  elements.skillSave.disabled = true;
  elements.skillRemovePack.disabled = true;
  elements.skillInstall.disabled = false;
});
elements.skillInstall.addEventListener("click", async () => {
  const response = await fetch(`/api/sessions/${sessionId}/attachments/${skillAttachmentId}/skill-install`, { method: "POST" });
  const payload = await response.json();
  if (!response.ok) return showError(payload.detail || "Skill installation failed");
  elements.skillConversionStatus.textContent = `Installed ${payload.name} with ${payload.skills.length} skills`;
  elements.skillInstall.disabled = true;
  await loadSkills();
});
elements.skillDeduplicate.addEventListener("click", async () => {
  const response = await fetch("/api/skills/deduplicate", { method: "POST" });
  const payload = await response.json();
  if (!response.ok) return showError(payload.detail || "Unable to remove duplicate skills");
  elements.skillConversionStatus.textContent = `Removed ${payload.removed_packs} duplicate packs and ${payload.removed_skills} duplicate skills`;
  await loadSkills();
});
elements.skillSave.addEventListener("click", async () => {
  if (!editingSkill) return;
  const response = await fetch(`/api/skills/${editingSkill.packId}/${editingSkill.skillId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: elements.skillEditor.value, enabled: elements.skillEnabled.checked }),
  });
  if (!response.ok) return showError((await response.json()).detail || "Unable to save skill");
  await loadSkills();
});
elements.skillRemovePack.addEventListener("click", async () => {
  if (!editingSkill || !confirm("Remove this installed skill pack? The imported archive will be preserved.")) return;
  const response = await fetch(`/api/skills/${editingSkill.packId}`, { method: "DELETE" });
  if (!response.ok) return showError((await response.json()).detail || "Unable to remove skill pack");
  editingSkill = null;
  elements.skillEditor.value = "";
  elements.skillEditor.disabled = true;
  elements.skillEnabled.disabled = true;
  elements.skillSave.disabled = true;
  elements.skillRemovePack.disabled = true;
  await loadSkills();
});
elements.terminalToggle.addEventListener("click", async () => {
  elements.terminalPanel.hidden = !elements.terminalPanel.hidden;
  elements.terminalToggle.setAttribute("aria-expanded", String(!elements.terminalPanel.hidden));
  localStorage.setItem("json_codr_terminal_open", String(!elements.terminalPanel.hidden));
  if (!elements.terminalPanel.hidden) {
    try { await ensureTerminal(); elements.terminalInput.focus(); }
    catch (error) { appendTerminalOutput(`Error: ${error.message}\n`); }
  }
});
elements.terminalRun.addEventListener("click", () => runTerminalCommand().catch((error) => appendTerminalOutput(`Error: ${error.message}\n`)));
elements.terminalInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") runTerminalCommand().catch((error) => appendTerminalOutput(`Error: ${error.message}\n`));
});
elements.terminalStop.addEventListener("click", () => {
  if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(JSON.stringify({ type: "interrupt" }));
});
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && !event.altKey && event.key.toLowerCase() === "j") {
    event.preventDefault();
    elements.terminalToggle.click();
  }
  if (event.ctrlKey && event.altKey && event.key.toLowerCase() === "b") {
    event.preventDefault();
    elements.contextToggle.click();
  }
});

loadApplication();
loadAttachments().catch((error) => showError(error.message));
