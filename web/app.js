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
  skillsToggle: document.querySelector("#skills-toggle"),
  skillsPanel: document.querySelector("#skills-panel"),
  settingsToggle: document.querySelector("#settings-toggle"),
  settingsPanel: document.querySelector("#settings-panel"),
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
  skillDetails: document.querySelector("#skill-details"),
  skillScanDirectory: document.querySelector("#skill-scan-directory"),
  skillScan: document.querySelector("#skill-scan"),
  skillScanKnown: document.querySelector("#skill-scan-known"),
  skillScanResults: document.querySelector("#skill-scan-results"),
  skillsetList: document.querySelector("#skillset-list"),
  skillRecommendations: document.querySelector("#skill-recommendations"),
  autoAttachSkills: document.querySelector("#auto-attach-skills"),
  attachedSkills: document.querySelector("#attached-skills"),
  actionReview: document.querySelector("#action-review"),
  actionList: document.querySelector("#action-list"),
  destructiveDialog: document.querySelector("#destructive-confirmation-dialog"),
  destructiveCommand: document.querySelector("#destructive-confirmation-command"),
  destructiveCwd: document.querySelector("#destructive-confirmation-cwd"),
  destructiveRisk: document.querySelector("#destructive-confirmation-risk"),
  destructivePhrase: document.querySelector("#destructive-confirmation-phrase"),
  destructiveInput: document.querySelector("#destructive-confirmation-input"),
  destructiveSubmit: document.querySelector("#destructive-confirmation-submit"),
  settingSkillsOpen: document.querySelector("#setting-skills-open"),
  settingTheme: document.querySelector("#setting-theme"),
  approvedSkillDirectories: document.querySelector("#approved-skill-directories"),
  hardwareStatus: document.querySelector("#hardware-status"),
  hardwareDetect: document.querySelector("#hardware-detect"),
  hardwareCandidates: document.querySelector("#hardware-candidates"),
  hardwareRestoreCpu: document.querySelector("#hardware-restore-cpu"),
  hardwareTabOptimization: document.querySelector("#hardware-tab-optimization"),
  hardwareTabBenchmarks: document.querySelector("#hardware-tab-benchmarks"),
  hardwareOptimizationView: document.querySelector("#hardware-optimization-view"),
  hardwareBenchmarkView: document.querySelector("#hardware-benchmark-view"),
  hardwareBenchmarkSuite: document.querySelector("#hardware-benchmark-suite"),
  hardwareBenchmarkModel: document.querySelector("#hardware-benchmark-model"),
  hardwareBenchmarkBackend: document.querySelector("#hardware-benchmark-backend"),
  hardwareBenchmarkRun: document.querySelector("#hardware-benchmark-run"),
  hardwareBenchmarkStatus: document.querySelector("#hardware-benchmark-status"),
  hardwareBenchmarkResults: document.querySelector("#hardware-benchmark-results"),
  hardwareBenchmarkHistory: document.querySelector("#hardware-benchmark-history"),
  terminalToggle: document.querySelector("#terminal-toggle"),
  terminalPanel: document.querySelector("#terminal-panel"),
  terminalOutput: document.querySelector("#terminal-output"),
  terminalInput: document.querySelector("#terminal-input"),
  terminalRun: document.querySelector("#terminal-run"),
  terminalStop: document.querySelector("#terminal-stop"),
  terminalStatus: document.querySelector("#terminal-status"),
};

const VALID_THEME_MODES = new Set(["light", "dark", "system"]);
const systemThemeQuery = window.matchMedia("(prefers-color-scheme: dark)");

let models = [];
let activeRequest = null;
let sessionId = localStorage.getItem("json_codr_session");
let terminalId = null;
let terminalSocket = null;
let skillAttachmentId = null;
let editingSkill = null;
let skillLoadGeneration = 0;
let settingsState = null;
let skillFallbackToken = null;
let settingsSaveQueue = Promise.resolve();
let themeSaveRevision = 0;
let skillsChangeRevision = 0;
let currentThemeMode = normalizeThemeMode(localStorage.getItem("json_codr_theme"));
let persistedThemeMode = null;
let excludedSkillIds = [];
let pendingDestructiveAction = null;

const dependencyInstallQueue = createDependencyInstallQueue(async (command) => {
  if (elements.terminalPanel.hidden) {
    elements.terminalPanel.hidden = false;
    elements.terminalToggle.setAttribute("aria-expanded", "true");
    localStorage.setItem("json_codr_terminal_open", "true");
  }
  elements.terminalStatus.textContent = "Installing prerequisites...";
  appendTerminalOutput(`Installing prerequisites: ${command}\n`);
  try {
    await runTerminalCommand(command);
  } catch (error) {
    appendTerminalOutput(`Error: ${error.message}\n`);
    throw error;
  }
});

function normalizeThemeMode(mode) {
  return VALID_THEME_MODES.has(mode) ? mode : "dark";
}

function applyThemeMode(mode, { cache = true } = {}) {
  const normalized = normalizeThemeMode(mode);
  const effective = normalized === "system" ? (systemThemeQuery.matches ? "dark" : "light") : normalized;
  currentThemeMode = normalized;
  document.documentElement.dataset.theme = effective;
  document.documentElement.style.colorScheme = effective;
  if (cache) localStorage.setItem("json_codr_theme", normalized);
  if (elements.settingTheme) elements.settingTheme.value = normalized;
  return effective;
}

systemThemeQuery.addEventListener("change", () => {
  if (currentThemeMode === "system") applyThemeMode("system", { cache: false });
});
applyThemeMode(currentThemeMode);

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
    if (message.type === "action_error") showError(message.error || "Approved action failed");
  });
  terminalSocket.addEventListener("close", () => { elements.terminalStatus.textContent = "Disconnected"; });
}

async function sendApprovedAction(proposal, token) {
  await ensureTerminal();
  if (terminalSocket.readyState !== WebSocket.OPEN) {
    await new Promise((resolve) => terminalSocket.addEventListener("open", resolve, { once: true }));
  }
  terminalSocket.send(JSON.stringify({ type: "approved_action", proposal_id: proposal.id, token }));
  elements.terminalPanel.hidden = false;
  elements.terminalToggle.setAttribute("aria-expanded", "true");
}

async function approveAction(proposal) {
  await ensureTerminal();
  const response = await fetch(`/api/sessions/${sessionId}/action-proposals/${proposal.id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-JSON-CODR": "1" },
    body: JSON.stringify({ terminal_id: terminalId }),
  });
  const approval = await response.json();
  if (!response.ok) throw new Error(approval.detail || "Unable to approve action");
  if (!approval.requires_confirmation) return sendApprovedAction(proposal, approval.token);
  pendingDestructiveAction = { proposal, phrase: approval.confirmation_phrase };
  elements.destructiveCommand.textContent = proposal.command;
  elements.destructiveCwd.textContent = proposal.cwd;
  elements.destructiveRisk.textContent = `${proposal.risk}: ${proposal.risk_reason}`;
  elements.destructivePhrase.textContent = approval.confirmation_phrase;
  elements.destructiveInput.value = "";
  elements.destructiveDialog.showModal();
  elements.destructiveInput.focus();
}

function renderActions(proposals) {
  elements.actionList.replaceChildren();
  elements.actionReview.hidden = !proposals.length;
  for (const proposal of proposals) {
    const card = document.createElement("article"); card.className = "action-card";
    const title = document.createElement("strong"); title.textContent = proposal.explanation;
    const command = document.createElement("code"); command.textContent = proposal.command;
    const cwd = document.createElement("small"); cwd.textContent = `Working directory: ${proposal.cwd}`;
    const risk = document.createElement("p"); risk.className = `action-risk ${proposal.risk}`;
    risk.textContent = `${proposal.risk.toUpperCase()} · ${proposal.risk_reason}`;
    const controls = document.createElement("div"); controls.className = "action-controls";
    const copy = document.createElement("button"); copy.type = "button"; copy.className = "secondary"; copy.textContent = "Copy";
    copy.addEventListener("click", () => navigator.clipboard.writeText(proposal.command));
    const reject = document.createElement("button"); reject.type = "button"; reject.className = "secondary"; reject.textContent = "Reject";
    reject.addEventListener("click", async () => {
      const response = await fetch(`/api/sessions/${sessionId}/action-proposals/${proposal.id}/reject`, { method: "POST" });
      if (!response.ok) return showError((await response.json()).detail || "Unable to reject action");
      card.remove();
      elements.actionReview.hidden = !elements.actionList.children.length;
    });
    const approve = document.createElement("button"); approve.type = "button"; approve.className = "primary"; approve.textContent = "Approve and run";
    approve.addEventListener("click", () => approveAction(proposal).catch((error) => showError(error.message)));
    controls.append(copy, reject, approve);
    card.append(title, command, cwd, risk, controls);
    elements.actionList.append(card);
  }
}

async function runTerminalCommand(command = null) {
  const fromInput = command === null;
  command = fromInput ? elements.terminalInput.value : command;
  if (!command.trim()) return;
  await ensureTerminal();
  if (terminalSocket.readyState !== WebSocket.OPEN) {
    await new Promise((resolve, reject) => {
      const cleanup = () => {
        terminalSocket.removeEventListener("open", onOpen);
        terminalSocket.removeEventListener("error", onFailure);
        terminalSocket.removeEventListener("close", onFailure);
      };
      const onOpen = () => { cleanup(); resolve(); };
      const onFailure = () => { cleanup(); reject(new Error("Terminal connection failed")); };
      terminalSocket.addEventListener("open", onOpen, { once: true });
      terminalSocket.addEventListener("error", onFailure, { once: true });
      terminalSocket.addEventListener("close", onFailure, { once: true });
    });
  }
  terminalSocket.send(JSON.stringify({ type: "input", data: `${command}\r\n` }));
  if (fromInput) elements.terminalInput.value = "";
}

async function ensureSession() {
  if (sessionId && (await fetch(`/api/sessions/${sessionId}`)).ok) return sessionId;
  const session = await fetch("/api/sessions", { method: "POST" }).then((response) => response.json());
  sessionId = session.id;
  localStorage.setItem("json_codr_session", sessionId);
  return sessionId;
}

async function persistSettings(update) {
  const response = await fetch("/api/settings", {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update),
  });
  if (!response.ok) throw new Error((await response.json()).detail || "Unable to save settings");
  settingsState = await response.json();
  persistedThemeMode = normalizeThemeMode(settingsState.ui.theme);
  renderApprovedDirectories();
}

function saveSettings(update) {
  const operation = settingsSaveQueue.then(() => persistSettings(update));
  settingsSaveQueue = operation.catch(() => undefined);
  return operation;
}

function queueSettingsLoad() {
  const operation = settingsSaveQueue.then(() => loadSettings());
  settingsSaveQueue = operation.catch(() => undefined);
  return operation;
}

function renderApprovedDirectories() {
  elements.approvedSkillDirectories.replaceChildren();
  const directories = settingsState?.skill_scan?.approved_directories || [];
  if (!directories.length) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No folders approved.";
    elements.approvedSkillDirectories.append(empty); return;
  }
  for (const directory of directories) {
    const row = document.createElement("div"); row.className = "dependency-row";
    const path = document.createElement("code"); path.textContent = directory;
    const actions = document.createElement("div"); actions.className = "attachment-actions";
    const rescan = document.createElement("button"); rescan.type = "button"; rescan.textContent = "Rescan";
    rescan.addEventListener("click", () => scanSkillDirectory(directory));
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Remove";
    remove.addEventListener("click", () => saveSettings({ skill_scan: { approved_directories: directories.filter((item) => item !== directory) } }).catch((error) => showError(error.message)));
    actions.append(rescan, remove); row.append(path, actions); elements.approvedSkillDirectories.append(row);
  }
}

async function loadSettings() {
  const themeRevisionAtStart = themeSaveRevision;
  const skillsRevisionAtStart = skillsChangeRevision;
  const response = await fetch("/api/settings");
  if (!response.ok) throw new Error("Unable to load settings");
  settingsState = await response.json();
  persistedThemeMode = normalizeThemeMode(settingsState.ui.theme);
  const open = settingsState.ui.skill_catalog_open;
  if (themeRevisionAtStart === themeSaveRevision) {
    applyThemeMode(persistedThemeMode);
  }
  if (skillsRevisionAtStart === skillsChangeRevision) {
    elements.skillsPanel.hidden = !open;
    elements.skillsToggle.setAttribute("aria-expanded", String(open));
    elements.settingSkillsOpen.checked = open;
  }
  elements.settingTheme.disabled = false;
  elements.settingSkillsOpen.disabled = false;
  renderApprovedDirectories();
}

async function loadHardwareStatus() {
  const response = await fetch("/api/hardware");
  if (!response.ok) throw new Error("Unable to load hardware status");
  const state = await response.json();
  elements.hardwareStatus.textContent = `Preferred: ${state.preferred_backend} · last known good: ${state.last_known_good}`;
  if (state.last_error) elements.hardwareStatus.textContent += ` · last failure: ${state.last_error}`;
}

async function detectHardware() {
  elements.hardwareDetect.disabled = true;
  elements.hardwareCandidates.innerHTML = '<p class="meta">Detecting local runtimes…</p>';
  try {
    const response = await fetch("/api/hardware/detect", { method: "POST" });
    if (!response.ok) throw new Error((await response.json()).detail || "Hardware detection failed");
    const candidates = await response.json();
    elements.hardwareBenchmarkBackend.replaceChildren();
    const all = document.createElement("option"); all.value = "all"; all.textContent = "All detected and available";
    elements.hardwareBenchmarkBackend.append(all);
    for (const candidate of candidates) {
      const option = document.createElement("option"); option.value = candidate.id;
      option.textContent = `${candidate.name}${candidate.runnable && candidate.compatible ? "" : " — unavailable"}`;
      option.disabled = !candidate.runnable || !candidate.compatible;
      elements.hardwareBenchmarkBackend.append(option);
    }
    elements.hardwareCandidates.replaceChildren();
    for (const candidate of candidates) {
      const row = document.createElement("div"); row.className = "dependency-row";
      const label = document.createElement("div");
      const name = document.createElement("strong"); name.textContent = candidate.name;
      const detail = document.createElement("p"); detail.className = "meta";
      detail.textContent = candidate.compatibility_reason || (candidate.verified ? "Verified" : candidate.quarantine_reason ? `Quarantined: ${candidate.quarantine_reason}` : "Available for testing");
      label.append(name, detail);
      const probe = document.createElement("button"); probe.type = "button"; probe.className = "secondary"; probe.textContent = "Test and use";
      if (candidate.runnable === false) { probe.disabled = true; probe.textContent = "Runtime unavailable"; }
      probe.addEventListener("click", async () => {
        probe.disabled = true; probe.textContent = "Testing…";
        try {
          const result = await fetch("/api/hardware/probe", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ backend: candidate.id, model: elements.model.value || "qwen2.5-coder:0.5b" }),
          });
          const payload = await result.json();
          if (!result.ok) throw new Error(payload.detail || "Backend probe failed");
          await loadHardwareStatus(); await detectHardware();
          if (payload.restart_required) elements.hardwareStatus.textContent += " · restart Ollama to activate";
        } catch (error) { showError(error.message); probe.disabled = false; probe.textContent = "Retest"; }
      });
      row.append(label, probe); elements.hardwareCandidates.append(row);
    }
  } finally { elements.hardwareDetect.disabled = false; }
}

async function restoreCpuBackend() {
  const response = await fetch("/api/hardware/restore-cpu", { method: "POST" });
  if (!response.ok) throw new Error((await response.json()).detail || "Unable to restore CPU mode");
  await loadHardwareStatus();
  elements.hardwareStatus.textContent += " · restart Ollama to activate";
}

function selectHardwareTab(tab) {
  const benchmarks = tab === "benchmarks";
  elements.hardwareOptimizationView.hidden = benchmarks;
  elements.hardwareBenchmarkView.hidden = !benchmarks;
  elements.hardwareTabOptimization.setAttribute("aria-selected", String(!benchmarks));
  elements.hardwareTabBenchmarks.setAttribute("aria-selected", String(benchmarks));
}

function renderBenchmarkResults(benchmark) {
  elements.hardwareBenchmarkResults.replaceChildren();
  for (const result of benchmark.results) {
    const row = document.createElement("div"); row.className = "dependency-row";
    const label = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = result.name;
    const metrics = document.createElement("p"); metrics.className = "meta";
    let components = null;
    if (result.status === "completed") {
      const relative = result.speedup_vs_cpu == null ? "CPU baseline unavailable" : `${result.speedup_vs_cpu.toFixed(2)}× CPU`;
      metrics.textContent = `${result.tokens_per_second.toFixed(2)} tokens/s · ${result.average_total_seconds.toFixed(3)}s average · ${relative}`;
      components = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${result.runtime} · ${result.kind} · ${result.verified ? "verified" : "not yet verified"}${result.active ? " · active" : ""}`;
      components.append(summary);
      for (const test of result.tests) {
        const line = document.createElement("p"); line.className = "meta";
        line.textContent = `${test.test} #${test.repetition}: ${test.total_seconds.toFixed(3)}s · ${test.load_seconds.toFixed(3)}s load · ${test.tokens} tokens · ${test.tokens_per_second.toFixed(2)} tokens/s`;
        components.append(line);
      }
    } else {
      metrics.textContent = `${result.status}: ${result.error || "Backend is unavailable"}`;
    }
    label.append(name, metrics);
    if (components) label.append(components);
    row.append(label); elements.hardwareBenchmarkResults.append(row);
  }
}

async function loadBenchmarkHistory() {
  const response = await fetch("/api/hardware/benchmarks");
  if (!response.ok) throw new Error("Unable to load benchmark history");
  const history = await response.json();
  elements.hardwareBenchmarkHistory.replaceChildren();
  if (!history.length) {
    elements.hardwareBenchmarkHistory.innerHTML = '<p class="meta">No benchmark history.</p>';
    return;
  }
  for (const benchmark of history) {
    const button = document.createElement("button"); button.type = "button"; button.className = "secondary";
    button.textContent = `${benchmark.suite} · ${benchmark.model} · ${new Date(benchmark.created_at).toLocaleString()}`;
    button.addEventListener("click", () => renderBenchmarkResults(benchmark));
    elements.hardwareBenchmarkHistory.append(button);
  }
  renderBenchmarkResults(history[0]);
}

async function runHardwareBenchmark() {
  elements.hardwareBenchmarkRun.disabled = true;
  elements.hardwareBenchmarkStatus.textContent = "Running standardized benchmark…";
  try {
    const response = await fetch("/api/hardware/benchmarks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suite: elements.hardwareBenchmarkSuite.value, model: elements.hardwareBenchmarkModel.value, backend: elements.hardwareBenchmarkBackend.value }),
    });
    const benchmark = await response.json();
    if (!response.ok) throw new Error(benchmark.detail || "Benchmark failed");
    renderBenchmarkResults(benchmark);
    await loadBenchmarkHistory();
    elements.hardwareBenchmarkStatus.textContent = "Benchmark complete";
  } finally {
    elements.hardwareBenchmarkRun.disabled = false;
  }
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

function showSkillDetails(pack, skill, selected) {
  elements.skillDetails.replaceChildren();
  elements.skillDetails.hidden = false;
  const title = document.createElement("h3"); title.textContent = skill.name;
  const state = document.createElement("p"); state.className = "meta";
  state.textContent = `${selected ? "Active in this session" : "Installed"} · ${skill.enabled ? "enabled" : "disabled"} · ${pack.source_format}`;
  const intent = document.createElement("p"); intent.textContent = skill.description || `Apply the ${skill.name} workflow to the current request.`;
  const abilities = document.createElement("pre");
  const capability = skill.content.match(/^(?:capabilities|required-capabilities):\s*([^\n]+)/mi);
  abilities.textContent = `ABILITIES\n${capability ? capability[1] : "Uses the instructions and capabilities available to the selected model."}\n\nCOMMAND STRUCTURE & SYNTAX\nSelect this skill, then describe the task in the prompt. {{arguments}} represents user input when present.\n\nEXAMPLE\nEnable the skill, save it, and run a relevant request with any installed LLM.`;
  const instructions = document.createElement("pre");
  instructions.textContent = `CONVERTED INSTRUCTIONS\n${skill.content}`;
  const download = document.createElement("a");
  download.className = "secondary file-button";
  download.href = `/api/skills/${pack.id}/${skill.id}/documentation.md`;
  download.textContent = "Export documentation";
  title.scrollIntoView({ block: "nearest" });
  elements.skillDetails.append(title, state, intent, abilities, instructions, download);
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
    const packHead = document.createElement("div"); packHead.className = "skill-pack-head";
    const rename = document.createElement("button"); rename.type = "button"; rename.textContent = "Rename pack";
    rename.addEventListener("click", async () => {
      const name = prompt("Rename this skill pack", pack.name);
      if (!name?.trim() || name.trim() === pack.name) return;
      const response = await fetch(`/api/skills/${pack.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }),
      });
      const result = await response.json();
      if (!response.ok) return showError(result.detail || "Unable to rename skill pack");
      elements.skillConversionStatus.textContent = `Renamed pack to ${result.name}`;
      await loadSkills();
    });
    packHead.append(heading, rename); group.append(packHead);
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
        editingSkill = { packId: pack.id, skillId: skill.id, name: skill.name, enabled: skill.enabled };
        elements.skillEditor.value = skill.content;
        elements.skillEditor.disabled = false;
        elements.skillEnabled.checked = skill.enabled;
        elements.skillEnabled.disabled = false;
        elements.skillSave.disabled = false;
        elements.skillRemovePack.disabled = false;
      });
      const details = document.createElement("button");
      details.type = "button";
      details.textContent = "Details";
      details.addEventListener("click", () => showSkillDetails(pack, skill, selected.has(checkbox.value)));
      const actions = document.createElement("div"); actions.className = "skill-actions"; actions.append(details, edit);
      row.append(label, actions);
      group.append(row);
    }
    content.append(group);
  }
  if (generation !== skillLoadGeneration) return;
  elements.skillList.replaceChildren(content);
}

async function loadSkillsets() {
  await ensureSession();
  const [skillsetResponse, sessionResponse] = await Promise.all([
    fetch("/api/skillsets"),
    fetch(`/api/sessions/${sessionId}`),
  ]);
  const skillsets = await skillsetResponse.json();
  const session = await sessionResponse.json();
  if (!skillsetResponse.ok) throw new Error(skillsets.detail || "Unable to load Skillsets");
  excludedSkillIds = session.excluded_skill_ids || [];
  elements.autoAttachSkills.checked = session.auto_attach_skills !== false;
  elements.skillsetList.replaceChildren();
  for (const skillset of skillsets) {
    const details = document.createElement("details"); details.className = "skillset-pack";
    const summary = document.createElement("summary");
    summary.textContent = `${skillset.name} · ${skillset.members.length} skills`;
    const description = document.createElement("p"); description.textContent = skillset.summary;
    const members = document.createElement("ul");
    for (const member of skillset.members) {
      const item = document.createElement("li"); item.textContent = member.name; members.append(item);
    }
    details.append(summary, description, members);
    elements.skillsetList.append(details);
  }
  if (!skillsets.length) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No Skillsets available.";
    elements.skillsetList.append(empty);
  }
}

function renderRecommendations(recommendations) {
  elements.skillRecommendations.replaceChildren();
  for (const recommendation of recommendations) {
    const row = document.createElement("div"); row.className = "recommendation-row";
    const explanation = document.createElement("span");
    explanation.textContent = `${recommendation.name} · ${recommendation.reasons.join(" · ")}`;
    row.append(explanation);
    if (!recommendation.manual) {
      const button = document.createElement("button"); button.type = "button"; button.className = "secondary"; button.textContent = "Dismiss";
      button.addEventListener("click", async () => {
        excludedSkillIds = [...new Set([...excludedSkillIds, recommendation.reference])];
        const response = await fetch(`/api/sessions/${sessionId}/skill-routing`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ excluded_skill_ids: excludedSkillIds }),
        });
        if (!response.ok) return showError((await response.json()).detail || "Unable to dismiss recommendation");
        row.remove();
      });
      row.append(button);
    }
    elements.skillRecommendations.append(row);
  }
}

async function previewSkillRecommendations() {
  const prompt = elements.prompt.value.trim();
  if (!prompt) return renderRecommendations([]);
  await ensureSession();
  const response = await fetch(`/api/sessions/${sessionId}/skill-recommendations`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Unable to preview skill recommendations");
  renderRecommendations(payload.recommendations || []);
}

function renderAttachedSkills(skills) {
  elements.attachedSkills.replaceChildren();
  elements.attachedSkills.hidden = !skills.length;
  for (const skill of skills) {
    const chip = document.createElement("span"); chip.className = "attached-skill-chip";
    chip.textContent = `${skill.name} · ${skill.reasons.join(" · ")}`;
    elements.attachedSkills.append(chip);
  }
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
    if (suggestion.automatic) dependencyInstallQueue.enqueue(suggestion.command);
  }
}

function renderSkillDiscoveries(payload) {
  elements.skillScanResults.replaceChildren();
  skillFallbackToken = payload.fallback_token || null;
  elements.skillScanKnown.hidden = !skillFallbackToken;
  for (const warning of payload.warnings || []) {
    const notice = document.createElement("p"); notice.className = "meta"; notice.textContent = warning;
    elements.skillScanResults.append(notice);
  }
  if (!payload.discoveries.length) {
    const empty = document.createElement("p"); empty.className = "meta";
    empty.textContent = "No compatible skills found. You may scan known provider locations.";
    elements.skillScanResults.append(empty); return;
  }
  for (const discovery of payload.discoveries) {
    const row = document.createElement("div"); row.className = "dependency-row";
    const description = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = discovery.name;
    const metadata = document.createElement("span"); metadata.className = "meta";
    metadata.textContent = `${discovery.source_format} · ${discovery.skill_count} skill(s)${discovery.already_installed ? " · already installed" : ""}`;
    description.append(name, metadata);
    const install = document.createElement("button"); install.type = "button"; install.className = "secondary"; install.textContent = "Install";
    install.disabled = discovery.already_installed;
    install.addEventListener("click", async () => {
      const response = await fetch("/api/skills/install-discovery", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ discovery_id: discovery.id }),
      });
      const result = await response.json();
      if (!response.ok) return showError(result.detail || "Unable to install discovered skill");
      elements.skillConversionStatus.textContent = `Installed ${result.name} with ${result.skills.length} skills`;
      await loadSkills();
      install.disabled = true;
    });
    row.append(description, install); elements.skillScanResults.append(row);
  }
}

async function scanSkillDirectory(directory = elements.skillScanDirectory.value) {
  if (!directory.trim()) return showError("Enter a local skill directory to scan");
  elements.skillScanDirectory.value = directory;
  const response = await fetch("/api/skills/scan", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ directory }),
  });
  const payload = await response.json();
  if (!response.ok) return showError(payload.detail || "Skill scan failed");
  renderSkillDiscoveries(payload);
  await queueSettingsLoad();
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
      if (model.installed) elements.hardwareBenchmarkModel.append(option.cloneNode(true));
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
    renderAttachedSkills(payload.attached_skills || []);
    renderRecommendations(payload.skill_recommendations || []);
    renderActions(payload.action_proposals || []);
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
let recommendationTimer = null;
elements.prompt.addEventListener("input", () => {
  clearTimeout(recommendationTimer);
  recommendationTimer = setTimeout(() => previewSkillRecommendations().catch((error) => showError(error.message)), 300);
});
elements.autoAttachSkills.addEventListener("change", async () => {
  const response = await fetch(`/api/sessions/${sessionId}/skill-routing`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_attach_skills: elements.autoAttachSkills.checked }),
  });
  if (!response.ok) return showError((await response.json()).detail || "Unable to update automatic attachment");
  await previewSkillRecommendations();
});
elements.destructiveSubmit.addEventListener("click", async () => {
  if (!pendingDestructiveAction) return;
  const { proposal, phrase } = pendingDestructiveAction;
  if (elements.destructiveInput.value !== phrase) return showError("Confirmation phrase does not match");
  const response = await fetch(`/api/sessions/${sessionId}/action-proposals/${proposal.id}/confirm-destructive`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-JSON-CODR": "1" },
    body: JSON.stringify({ terminal_id: terminalId, phrase: elements.destructiveInput.value }),
  });
  const approval = await response.json();
  if (!response.ok) return showError(approval.detail || "Unable to confirm destructive action");
  elements.destructiveDialog.close();
  pendingDestructiveAction = null;
  await sendApprovedAction(proposal, approval.token);
});
elements.contextToggle.addEventListener("click", () => {
  elements.contextPanel.hidden = !elements.contextPanel.hidden;
  elements.contextToggle.setAttribute("aria-expanded", String(!elements.contextPanel.hidden));
  localStorage.setItem("json_codr_context_open", String(!elements.contextPanel.hidden));
});
elements.skillsToggle.addEventListener("click", () => {
  skillsChangeRevision += 1;
  const open = elements.skillsPanel.hidden;
  elements.skillsPanel.hidden = !open;
  elements.skillsToggle.setAttribute("aria-expanded", String(open));
  elements.settingSkillsOpen.checked = open;
  saveSettings({ ui: { skill_catalog_open: open } }).catch((error) => showError(error.message));
});
elements.settingsToggle.addEventListener("click", () => {
  const open = elements.settingsPanel.hidden;
  elements.settingsPanel.hidden = !open;
  elements.settingsToggle.setAttribute("aria-expanded", String(open));
  if (open) {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    elements.settingsPanel.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    elements.settingTheme.focus({ preventScroll: true });
  }
});
elements.hardwareDetect.addEventListener("click", () => detectHardware().catch((error) => showError(error.message)));
elements.hardwareRestoreCpu.addEventListener("click", () => restoreCpuBackend().catch((error) => showError(error.message)));
elements.hardwareTabOptimization.addEventListener("click", () => selectHardwareTab("optimization"));
elements.hardwareTabBenchmarks.addEventListener("click", () => {
  selectHardwareTab("benchmarks");
  detectHardware().catch((error) => showError(error.message));
  loadBenchmarkHistory().catch((error) => showError(error.message));
});
elements.hardwareBenchmarkRun.addEventListener("click", () => runHardwareBenchmark().catch((error) => {
  elements.hardwareBenchmarkStatus.textContent = error.message;
  showError(error.message);
}));
elements.settingSkillsOpen.addEventListener("change", () => {
  skillsChangeRevision += 1;
  const open = elements.settingSkillsOpen.checked;
  elements.skillsPanel.hidden = !open;
  elements.skillsToggle.setAttribute("aria-expanded", String(open));
  saveSettings({ ui: { skill_catalog_open: open } }).catch((error) => showError(error.message));
});
elements.settingTheme.addEventListener("change", async () => {
  const revision = ++themeSaveRevision;
  const nextThemeMode = normalizeThemeMode(elements.settingTheme.value);
  applyThemeMode(nextThemeMode);
  try {
    await saveSettings({ ui: { theme: nextThemeMode } });
  } catch (error) {
    if (revision === themeSaveRevision) {
      applyThemeMode(persistedThemeMode || "dark");
    }
    showError(error.message);
  }
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
elements.skillScan.addEventListener("click", () => scanSkillDirectory().catch((error) => showError(error.message)));
elements.skillScanKnown.addEventListener("click", async () => {
  if (!skillFallbackToken || !confirm("No skills were found. Scan known Claude, Codex, and JSON_CODR locations now?")) return;
  const response = await fetch("/api/skills/scan-known", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fallback_token: skillFallbackToken }),
  });
  const payload = await response.json();
  if (!response.ok) return showError(payload.detail || "Known-location scan failed");
  renderSkillDiscoveries(payload);
});
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
  elements.skillSave.disabled = true;
  const response = await fetch(`/api/skills/${editingSkill.packId}/${editingSkill.skillId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: elements.skillEditor.value,
      enabled: elements.skillEnabled.checked,
      session_id: sessionId,
    }),
  });
  if (!response.ok) {
    elements.skillSave.disabled = false;
    return showError((await response.json()).detail || "Unable to save skill");
  }
  elements.skillConversionStatus.textContent = elements.skillEnabled.checked
    ? `Saved and applied ${editingSkill.name} to this session`
    : `Saved and disabled ${editingSkill.name}`;
  if (elements.skillsPanel.hidden) {
    elements.skillsPanel.hidden = false;
    elements.skillsToggle.setAttribute("aria-expanded", "true");
    elements.settingSkillsOpen.checked = true;
    skillsChangeRevision += 1;
    await saveSettings({ ui: { skill_catalog_open: true } });
  }
  await loadSkills();
  elements.skillSave.disabled = false;
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
queueSettingsLoad().catch((error) => showError(error.message));
loadHardwareStatus().catch((error) => showError(error.message));
loadAttachments().catch((error) => showError(error.message));
loadSkillsets().catch((error) => showError(error.message));
