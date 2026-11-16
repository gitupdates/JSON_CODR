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
  appSidebar: document.querySelector("#app-sidebar"),
  sidebarCollapse: document.querySelector("#sidebar-collapse"),
  sidebarResizeHandle: document.querySelector("#sidebar-resize-handle"),
  mobileNavigationToggle: document.querySelector("#mobile-navigation-toggle"),
  navigationBackdrop: document.querySelector("#navigation-backdrop"),
  navigationButtons: [...document.querySelectorAll("[data-destination]")],
  destinationViews: [...document.querySelectorAll("[data-view]")],
  hardwareSubnavigation: document.querySelector("#hardware-subnavigation"),
  hardwareSectionButtons: [...document.querySelectorAll("[data-hardware-section]")],
  hardwareSectionViews: [...document.querySelectorAll("[data-hardware-view]")],
  contextPanel: document.querySelector("#context-panel"),
  skillsPanel: document.querySelector("#skills-panel"),
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
  hardwareTelemetry: document.querySelector("#hardware-telemetry"),
  hardwareProfileModel: document.querySelector("#hardware-profile-model"),
  hardwareProfileMode: document.querySelector("#hardware-profile-mode"),
  hardwareProfileAdvanced: document.querySelector("#hardware-profile-advanced"),
  hardwareProfileNumGpu: document.querySelector("#hardware-profile-num-gpu"),
  hardwareProfileMainGpu: document.querySelector("#hardware-profile-main-gpu"),
  hardwareProfileNumCtx: document.querySelector("#hardware-profile-num-ctx"),
  hardwareProfileNumBatch: document.querySelector("#hardware-profile-num-batch"),
  hardwareProfileSave: document.querySelector("#hardware-profile-save"),
  hardwareProfileReset: document.querySelector("#hardware-profile-reset"),
  hardwareProfileStatus: document.querySelector("#hardware-profile-status"),
  hardwareRestoreCpu: document.querySelector("#hardware-restore-cpu"),
  hardwareModelCompatibility: document.querySelector("#hardware-model-compatibility"),
  hardwareBenchmarkSuite: document.querySelector("#hardware-benchmark-suite"),
  hardwareBenchmarkModel: document.querySelector("#hardware-benchmark-model"),
  hardwareBenchmarkBackend: document.querySelector("#hardware-benchmark-backend"),
  hardwareBenchmarkRun: document.querySelector("#hardware-benchmark-run"),
  hardwareBenchmarkStatus: document.querySelector("#hardware-benchmark-status"),
  hardwareBenchmarkResults: document.querySelector("#hardware-benchmark-results"),
  hardwareBenchmarkHistory: document.querySelector("#hardware-benchmark-history"),
  hardwareBenchmarkClear: document.querySelector("#hardware-benchmark-clear"),
  integrityBenchmarkSuite: document.querySelector("#integrity-benchmark-suite"),
  integrityBenchmarkModel: document.querySelector("#integrity-benchmark-model"),
  integrityBenchmarkRun: document.querySelector("#integrity-benchmark-run"),
  integrityBenchmarkStatus: document.querySelector("#integrity-benchmark-status"),
  integrityBenchmarkScores: document.querySelector("#integrity-benchmark-scores"),
  integrityBenchmarkResults: document.querySelector("#integrity-benchmark-results"),
  integrityBenchmarkHistory: document.querySelector("#integrity-benchmark-history"),
  leaderboardSearch: document.querySelector("#leaderboard-search"),
  leaderboardModelFilter: document.querySelector("#leaderboard-model-filter"),
  leaderboardBackendFilter: document.querySelector("#leaderboard-backend-filter"),
  leaderboardSuiteFilter: document.querySelector("#leaderboard-suite-filter"),
  leaderboardMetric: document.querySelector("#leaderboard-metric"),
  leaderboardKpis: document.querySelector("#leaderboard-kpis"),
  leaderboardTable: document.querySelector("#leaderboard-table"),
  leaderboardSortButtons: [...document.querySelectorAll("[data-sort-key]")],
  leaderboardBackendChart: document.querySelector("#leaderboard-backend-chart"),
  leaderboardTrendChart: document.querySelector("#leaderboard-trend-chart"),
  leaderboardDetails: document.querySelector("#leaderboard-details"),
  leaderboardStatus: document.querySelector("#leaderboard-status"),
  localperfExport: document.querySelector("#localperf-export"),
  localperfIncludeDetails: document.querySelector("#localperf-include-details"),
  localperfImportInput: document.querySelector("#localperf-import-input"),
  localperfImport: document.querySelector("#localperf-import"),
  localperfRetainDetails: document.querySelector("#localperf-retain-details"),
  localperfPackageStatus: document.querySelector("#localperf-package-status"),
  optimizedModelSearchProvider: document.querySelector("#optimized-model-search-provider"),
  optimizedModelSearchQuery: document.querySelector("#optimized-model-search-query"),
  optimizedModelSearchRun: document.querySelector("#optimized-model-search-run"),
  optimizedModelSearchResults: document.querySelector("#optimized-model-search-results"),
  terminalPanel: document.querySelector("#terminal-panel"),
  terminalOutput: document.querySelector("#terminal-output"),
  terminalInput: document.querySelector("#terminal-input"),
  terminalRun: document.querySelector("#terminal-run"),
  terminalStop: document.querySelector("#terminal-stop"),
  terminalStatus: document.querySelector("#terminal-status"),
};

const VALID_THEME_MODES = new Set(["light", "dark", "system"]);
const NAVIGATION_DESTINATIONS = new Set(["chat", "terminal", "context", "skills", "hardware", "settings"]);
const HARDWARE_SECTIONS = new Set(["overview", "profiles", "runtimes", "compatibility", "model-search", "benchmarks", "leaderboard", "history", "localperf"]);
const systemThemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
const narrowNavigationQuery = window.matchMedia("(max-width: 700px)");

let models = [];
let activeRequest = null;
let sessionId = localStorage.getItem("json_codr_session");
let terminalId = null;
let terminalSocket = null;
let selectedLocalperfEvaluationId = null;
let pendingLocalperfPackage = null;
let terminalConnectionPromise = null;
let skillAttachmentId = null;
let editingSkill = null;
let skillLoadGeneration = 0;
let settingsState = null;
let skillFallbackToken = null;
let settingsSaveQueue = Promise.resolve();
let themeSaveRevision = 0;
let skillsChangeRevision = 0;
let navigationChangeRevision = 0;
let activeDestination = "chat";
let activeHardwareSection = "overview";
let sidebarWidth = 260;
let currentThemeMode = normalizeThemeMode(localStorage.getItem("json_codr_theme"));
let persistedThemeMode = null;
let excludedSkillIds = [];
let pendingDestructiveAction = null;
let pendingActionProposalId = null;
let hardwareDetectionPromise = null;
let leaderboardHistoryCache = [];
let integrityHistoryCache = [];
let leaderboardCandidateCache = [];
let selectedLeaderboardSessionId = null;
let selectedLeaderboardRowId = null;
let leaderboardSort = { key: "rank", direction: "asc" };
const actionButtons = new Map();

const dependencyInstallQueue = createDependencyInstallQueue(async (command) => {
  selectDestination("terminal");
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

function boundedSidebarWidth(value) {
  return Math.max(220, Math.min(380, Math.round(Number(value) || 260)));
}

function applySidebarWidth(value) {
  const width = boundedSidebarWidth(value);
  sidebarWidth = width;
  document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
  elements.sidebarResizeHandle.setAttribute("aria-valuenow", String(width));
  return width;
}

function closeNavigationDrawer({ restoreFocus = false } = {}) {
  document.body.classList.remove("navigation-open");
  elements.navigationBackdrop.hidden = true;
  elements.mobileNavigationToggle.setAttribute("aria-expanded", "false");
  if (restoreFocus) elements.mobileNavigationToggle.focus();
}

function openNavigationDrawer() {
  document.body.classList.add("navigation-open");
  elements.navigationBackdrop.hidden = false;
  elements.mobileNavigationToggle.setAttribute("aria-expanded", "true");
}

function setSidebarCollapsed(collapsed, { persist = true } = {}) {
  navigationChangeRevision += persist ? 1 : 0;
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  elements.sidebarCollapse.setAttribute("aria-expanded", String(!collapsed));
  elements.sidebarCollapse.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
  if (persist) saveSettings({ ui: { sidebar_collapsed: collapsed } }).catch((error) => showError(error.message));
}

function selectHardwareSection(section, { persist = true, focus = false } = {}) {
  if (!HARDWARE_SECTIONS.has(section)) section = "overview";
  activeHardwareSection = section;
  for (const button of elements.hardwareSectionButtons) {
    if (button.dataset.hardwareSection === section) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const view of elements.hardwareSectionViews) view.hidden = view.dataset.hardwareView !== section;
  if (focus) document.querySelector(`[data-hardware-view="${section}"] h3`)?.focus({ preventScroll: true });
  if (section === "overview") loadHardwareTelemetry().catch((error) => showError(error.message));
  if (section === "runtimes" || section === "compatibility" || section === "benchmarks") {
    detectHardware().catch((error) => showError(error.message));
  }
  if (section === "benchmarks" || section === "history") loadBenchmarkHistory().catch((error) => showError(error.message));
  if (section === "benchmarks") loadIntegrityBenchmarkHistory().catch((error) => showError(error.message));
  if (section === "leaderboard") loadBenchmarkLeaderboard().catch((error) => { elements.leaderboardStatus.textContent = error.message; });
  if (persist) {
    navigationChangeRevision += 1;
    saveSettings({ ui: { hardware_section: section } }).catch((error) => showError(error.message));
  }
}

function selectDestination(destination, { persist = true, focus = false } = {}) {
  if (!NAVIGATION_DESTINATIONS.has(destination)) destination = "chat";
  activeDestination = destination;
  for (const button of elements.navigationButtons) {
    const selected = button.dataset.destination === destination;
    button.classList.toggle("is-active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const view of elements.destinationViews) view.hidden = view.dataset.view !== destination;
  elements.hardwareSubnavigation.hidden = destination !== "hardware";
  if (destination === "hardware") selectHardwareSection(activeHardwareSection, { persist: false });
  if (destination === "terminal") {
    ensureTerminal().then(() => elements.terminalInput.focus()).catch((error) => appendTerminalOutput(`Error: ${error.message}\n`));
  }
  if (focus) elements.destinationViews.find((view) => view.dataset.view === destination)?.querySelector("h1, h2, h3")?.focus({ preventScroll: true });
  if (narrowNavigationQuery.matches) closeNavigationDrawer();
  if (persist) {
    navigationChangeRevision += 1;
    skillsChangeRevision += 1;
    elements.settingSkillsOpen.checked = destination === "skills";
    saveSettings({ ui: { primary_destination: destination, skill_catalog_open: destination === "skills" } }).catch((error) => showError(error.message));
  }
}

function appendTerminalOutput(text) {
  elements.terminalOutput.textContent += text;
  elements.terminalOutput.scrollTop = elements.terminalOutput.scrollHeight;
}

async function ensureTerminal() {
  if (terminalSocket?.readyState === WebSocket.OPEN) return;
  if (terminalConnectionPromise) return terminalConnectionPromise;
  terminalConnectionPromise = createTerminalConnection();
  try {
    await terminalConnectionPromise;
  } finally {
    terminalConnectionPromise = null;
  }
}

async function createTerminalConnection() {
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
    if (message.type === "action_started") {
      if (pendingActionProposalId === message.proposal_id) pendingActionProposalId = null;
      elements.terminalStatus.textContent = "Command accepted — installation running...";
      appendTerminalOutput("Command accepted by PowerShell. Installation is running; initial setup may be quiet.\n");
      const button = actionButtons.get(message.proposal_id);
      if (button) button.textContent = "Started";
    }
    if (message.type === "action_completed") {
      elements.terminalOutput.textContent = elements.terminalOutput.textContent.replace(
        new RegExp(`__JSON_CODR_ACTION_DONE__:${message.proposal_id}:-?\\d+\\r?\\n?`, "g"),
        "",
      );
      elements.terminalStatus.textContent = message.success ? "Installation complete" : "Installation finished with errors";
      appendTerminalOutput(message.success
        ? "Approved installation completed successfully.\n"
        : `Approved installation finished with exit code ${message.exit_code}. Review the output above.\n`);
      const button = actionButtons.get(message.proposal_id);
      if (button) {
        button.disabled = message.success;
        button.textContent = message.success ? "Completed" : "Retry";
      }
    }
    if (message.type === "action_error") {
      if (pendingActionProposalId === message.proposal_id) pendingActionProposalId = null;
      const button = actionButtons.get(message.proposal_id);
      if (button) { button.disabled = false; button.textContent = "Approve and run"; }
      elements.terminalStatus.textContent = "Approved action failed";
      appendTerminalOutput(`Approved action failed: ${message.error || "Unknown error"}\n`);
      showError(message.error || "Approved action failed");
    }
  });
  terminalSocket.addEventListener("close", () => {
    if (pendingActionProposalId) {
      const button = actionButtons.get(pendingActionProposalId);
      if (button) { button.disabled = false; button.textContent = "Approve and run"; }
      appendTerminalOutput("Terminal disconnected before action was accepted. Retry the approved action.\n");
      showError("Terminal disconnected before action was accepted");
      pendingActionProposalId = null;
    }
    elements.terminalStatus.textContent = "Disconnected";
  });
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

async function sendApprovedAction(proposal, token, approveButton) {
  await ensureTerminal();
  if (terminalSocket.readyState !== WebSocket.OPEN) {
    await new Promise((resolve) => terminalSocket.addEventListener("open", resolve, { once: true }));
  }
  elements.terminalStatus.textContent = "Sending approved action...";
  appendTerminalOutput(`Sending approved action: ${proposal.explanation}\n`);
  if (approveButton) { approveButton.disabled = true; approveButton.textContent = "Sending..."; }
  pendingActionProposalId = proposal.id;
  try {
    terminalSocket.send(JSON.stringify({ type: "approved_action", proposal_id: proposal.id, token }));
  } catch (error) {
    pendingActionProposalId = null;
    if (approveButton) { approveButton.disabled = false; approveButton.textContent = "Approve and run"; }
    throw error;
  }
  elements.terminalPanel.hidden = false;
  selectDestination("terminal");
}

async function approveAction(proposal, approveButton) {
  await ensureTerminal();
  const response = await fetch(`/api/sessions/${sessionId}/action-proposals/${proposal.id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-JSON-CODR": "1" },
    body: JSON.stringify({ terminal_id: terminalId }),
  });
  const approval = await response.json();
  if (!response.ok) throw new Error(approval.detail || "Unable to approve action");
  if (!approval.requires_confirmation) return sendApprovedAction(proposal, approval.token, approveButton);
  pendingDestructiveAction = { proposal, phrase: approval.confirmation_phrase, approveButton };
  approveButton.textContent = "Confirm to run";
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
  actionButtons.clear();
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
    actionButtons.set(proposal.id, approve);
    approve.addEventListener("click", async () => {
      approve.disabled = true;
      approve.textContent = "Connecting...";
      try {
        await approveAction(proposal, approve);
      } catch (error) {
        approve.disabled = false;
        approve.textContent = "Approve and run";
        showError(error.message);
      }
    });
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

function selectedGpuProfile() {
  const optimization = settingsState?.gpu_optimization;
  if (!optimization) return { mode: "automatic" };
  const target = elements.hardwareProfileModel.value;
  return target === "__default__"
    ? optimization.default_profile
    : optimization.model_profiles[target] || optimization.default_profile;
}

function renderGpuProfileControls() {
  const selectedTarget = elements.hardwareProfileModel.value || "__default__";
  elements.hardwareProfileModel.replaceChildren();
  const defaultOption = document.createElement("option");
  defaultOption.value = "__default__"; defaultOption.textContent = "All models · default";
  elements.hardwareProfileModel.append(defaultOption);
  for (const model of models.filter((item) => item.installed)) {
    const option = document.createElement("option"); option.value = model.name; option.textContent = model.name;
    elements.hardwareProfileModel.append(option);
  }
  elements.hardwareProfileModel.value = [...elements.hardwareProfileModel.options].some((item) => item.value === selectedTarget)
    ? selectedTarget : "__default__";
  const profile = selectedGpuProfile();
  elements.hardwareProfileMode.value = profile.mode;
  elements.hardwareProfileAdvanced.hidden = profile.mode !== "advanced";
  elements.hardwareProfileNumGpu.value = profile.num_gpu ?? "";
  elements.hardwareProfileMainGpu.value = profile.main_gpu ?? "";
  elements.hardwareProfileNumCtx.value = profile.num_ctx ?? "";
  elements.hardwareProfileNumBatch.value = profile.num_batch ?? "";
}

function numericProfileValue(element) {
  return element.value === "" ? null : Number(element.value);
}

async function saveGpuProfile(reset = false) {
  const current = settingsState.gpu_optimization;
  const target = elements.hardwareProfileModel.value;
  const mode = reset ? "automatic" : elements.hardwareProfileMode.value;
  const profile = { mode, num_gpu: null, main_gpu: null, num_ctx: null, num_batch: null };
  if (mode === "advanced") {
    profile.num_gpu = numericProfileValue(elements.hardwareProfileNumGpu);
    profile.main_gpu = numericProfileValue(elements.hardwareProfileMainGpu);
    profile.num_ctx = numericProfileValue(elements.hardwareProfileNumCtx);
    profile.num_batch = numericProfileValue(elements.hardwareProfileNumBatch);
  }
  const update = {
    default_profile: { ...current.default_profile },
    model_profiles: { ...current.model_profiles },
  };
  if (target === "__default__") update.default_profile = profile;
  else if (reset) delete update.model_profiles[target];
  else update.model_profiles[target] = profile;
  elements.hardwareProfileSave.disabled = true;
  elements.hardwareProfileStatus.textContent = "Saving…";
  try {
    await saveSettings({ gpu_optimization: update });
    elements.hardwareProfileStatus.textContent = reset ? "Automatic profile restored" : "Profile saved";
    renderGpuProfileControls();
  } finally {
    elements.hardwareProfileSave.disabled = false;
  }
}

async function loadHardwareTelemetry() {
  elements.hardwareTelemetry.innerHTML = '<p class="meta">Reading GPU and Ollama runtime data…</p>';
  const response = await fetch("/api/hardware/telemetry");
  if (!response.ok) throw new Error("Unable to load hardware telemetry");
  const payload = await response.json();
  elements.hardwareTelemetry.replaceChildren();
  if (!payload.gpus.length && !payload.models.length) {
    elements.hardwareTelemetry.innerHTML = '<p class="meta">No active GPU or loaded Ollama model telemetry.</p>';
    return;
  }
  for (const gpu of payload.gpus) {
    const row = document.createElement("div"); row.className = "dependency-row";
    const label = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = `GPU ${gpu.index} · ${gpu.name}`;
    const detail = document.createElement("p"); detail.className = "meta";
    detail.textContent = `${gpu.memory_free.toLocaleString()} MiB free of ${gpu.memory_total.toLocaleString()} MiB · ${gpu.utilization}% load · ${gpu.temperature}°C`;
    label.append(name, detail); row.append(label); elements.hardwareTelemetry.append(row);
  }
  for (const model of payload.models) {
    const row = document.createElement("div"); row.className = "dependency-row";
    const label = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = model.name;
    const detail = document.createElement("p"); detail.className = "meta";
    detail.textContent = `${model.processor} · ${(model.size_vram / 1048576).toFixed(0)} MiB VRAM`;
    label.append(name, detail); row.append(label); elements.hardwareTelemetry.append(row);
  }
}

async function loadSettings() {
  const themeRevisionAtStart = themeSaveRevision;
  const skillsRevisionAtStart = skillsChangeRevision;
  const navigationRevisionAtStart = navigationChangeRevision;
  const response = await fetch("/api/settings");
  if (!response.ok) throw new Error("Unable to load settings");
  settingsState = await response.json();
  persistedThemeMode = normalizeThemeMode(settingsState.ui.theme);
  if (themeRevisionAtStart === themeSaveRevision) {
    applyThemeMode(persistedThemeMode);
  }
  if (navigationRevisionAtStart === navigationChangeRevision) {
    applySidebarWidth(settingsState.ui.sidebar_width);
    setSidebarCollapsed(settingsState.ui.sidebar_collapsed, { persist: false });
    selectHardwareSection(settingsState.ui.hardware_section, { persist: false });
    selectDestination(settingsState.ui.primary_destination, { persist: false });
  }
  if (skillsRevisionAtStart === skillsChangeRevision) {
    elements.settingSkillsOpen.checked = settingsState.ui.primary_destination === "skills";
  }
  elements.settingTheme.disabled = false;
  elements.settingSkillsOpen.disabled = false;
  renderApprovedDirectories();
  renderGpuProfileControls();
}

async function loadHardwareStatus() {
  const response = await fetch("/api/hardware");
  if (!response.ok) throw new Error("Unable to load hardware status");
  const state = await response.json();
  elements.hardwareStatus.textContent = `Preferred: ${state.preferred_backend} · last known good: ${state.last_known_good}`;
  if (state.last_error) elements.hardwareStatus.textContent += ` · last failure: ${state.last_error}`;
}

function detectHardware() {
  if (hardwareDetectionPromise) return hardwareDetectionPromise;
  hardwareDetectionPromise = runHardwareDetection().finally(() => { hardwareDetectionPromise = null; });
  return hardwareDetectionPromise;
}

async function runHardwareDetection() {
  elements.hardwareDetect.disabled = true;
  elements.hardwareCandidates.innerHTML = '<p class="meta">Detecting local runtimes…</p>';
  try {
    const [response, catalogResponse, environmentResponse, compatibilityResponse] = await Promise.all([
      fetch("/api/hardware/detect", { method: "POST" }),
      fetch("/api/inference/catalog"),
      fetch("/api/inference/environments"),
      fetch("/api/hardware/model-compatibility"),
    ]);
    if (!response.ok) throw new Error((await response.json()).detail || "Hardware detection failed");
    const candidates = await response.json();
    leaderboardCandidateCache = candidates.map((candidate) => ({ ...candidate }));
    const optimizedCatalog = catalogResponse.ok ? await catalogResponse.json() : [];
    const providerEnvironments = environmentResponse.ok ? await environmentResponse.json() : [];
    const compatibility = compatibilityResponse.ok ? await compatibilityResponse.json() : [];
    elements.hardwareModelCompatibility.replaceChildren();
    if (!compatibility.length) {
      elements.hardwareModelCompatibility.innerHTML = '<p class="meta">No model-specific compatibility results are available.</p>';
    }
    for (const group of compatibility) {
      const row = document.createElement("div"); row.className = "dependency-row";
      const label = document.createElement("div");
      const name = document.createElement("strong"); name.textContent = group.backend_name || group.backend;
      label.append(name);
      for (const model of group.models || []) {
        const line = document.createElement("p"); line.className = "meta";
        const state = model.status === "accelerated" ? "Accelerated and verified" :
          model.status === "candidate" ? "Compatible download candidate" :
          model.status === "runnable" ? "Runnable · acceleration unverified" : model.status;
        line.textContent = `${model.model} · ${state}${model.reason ? ` · ${model.reason}` : ""}`;
        label.append(line);
      }
      row.append(label); elements.hardwareModelCompatibility.append(row);
    }
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
      const catalogCount = optimizedCatalog.filter((model) => model.provider === candidate.id).length;
      const stateDetails = candidate.hardware_detected !== undefined
        ? `hardware ${candidate.hardware_detected ? "detected" : "not detected"} · runtime ${candidate.runtime_ready ? "ready" : "missing"} · ${catalogCount} catalog model${catalogCount === 1 ? "" : "s"}`
        : null;
      const readiness = candidate.readiness
        ? `hardware ${candidate.readiness.hardware ? "ready" : "missing"} · driver ${candidate.readiness.driver ? "ready" : "missing"} · runtime ${candidate.readiness.runtime ? "ready" : "missing"} · model ${candidate.readiness.model ? "ready" : "missing"}`
        : null;
      detail.textContent = candidate.compatibility_reason || stateDetails || (candidate.verified ? `Verified · ${readiness}` : candidate.quarantine_reason ? `Quarantined: ${candidate.quarantine_reason}` : readiness || "Available for testing");
      label.append(name, detail);
      const compatibleModels = (candidate.compatible_models || []).filter((model) => model.status !== "unsupported");
      const readyModels = compatibleModels.filter((model) => ["runnable", "accelerated"].includes(model.status));
      let probeModel = elements.model.value || "qwen2.5-coder:0.5b";
      if (compatibleModels.length) {
        const modelDetails = document.createElement("details"); modelDetails.className = "runtime-models";
        const modelSummary = document.createElement("summary");
        modelSummary.textContent = `Compatible models (${compatibleModels.length}) · ${readyModels.length} ready`;
        modelDetails.append(modelSummary);
        for (const model of compatibleModels) {
          const line = document.createElement("p"); line.className = "meta";
          const state = model.status === "accelerated" ? "accelerated and verified" :
            model.status === "runnable" ? "ready to test" :
            model.status === "candidate" ? "available to download" : model.status;
          line.textContent = `${model.model} · ${state}${model.reason ? ` · ${model.reason}` : ""}`;
          modelDetails.append(line);
        }
        label.append(modelDetails);
      }
      const probe = document.createElement("button"); probe.type = "button"; probe.className = "secondary"; probe.textContent = "Test and use";
      if (candidate.runnable === false) { probe.disabled = true; probe.textContent = "Runtime unavailable"; }
      const modelSelect = document.createElement("select"); modelSelect.className = "runtime-model-select";
      modelSelect.setAttribute("aria-label", `${candidate.name} model to test`);
      for (const model of readyModels) {
        const option = document.createElement("option"); option.value = model.model; option.textContent = model.model;
        modelSelect.append(option);
      }
      if (readyModels.length) {
        probeModel = readyModels.some((model) => model.model === probeModel) ? probeModel : readyModels[0].model;
        modelSelect.value = probeModel;
        modelSelect.addEventListener("change", () => { probeModel = modelSelect.value; });
      } else if (candidate.runnable !== false) {
        probe.disabled = true;
        probe.textContent = "No ready model";
      }
      probe.addEventListener("click", async () => {
        probe.disabled = true; probe.textContent = "Testing…";
        try {
          const result = await fetch("/api/hardware/probe", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ backend: candidate.id, model: probeModel }),
          });
          const payload = await result.json();
          if (!result.ok) throw new Error(payload.detail || "Backend probe failed");
          await loadHardwareStatus(); await detectHardware();
          if (candidate.id === "ollama_gpu" && payload.verified) {
            elements.hardwareStatus.textContent += ` · GPU offload verified: ${payload.gpu_percent}% GPU · ${(payload.vram_bytes / 1048576).toFixed(0)} MiB VRAM`;
          }
          if (payload.restart_required) elements.hardwareStatus.textContent += " · restart Ollama to activate";
        } catch (error) { showError(error.message); probe.disabled = false; probe.textContent = "Retest"; }
      });
      const probeControls = document.createElement("div"); probeControls.className = "runtime-probe-controls";
      if (readyModels.length) probeControls.append(modelSelect);
      probeControls.append(probe);
      let control = probeControls;
      if (candidate.installation?.automatic) {
        const install = document.createElement("button"); install.type = "button"; install.className = "secondary"; install.textContent = "Review runtime install";
        install.addEventListener("click", async () => {
          try {
            await ensureSession();
            const response = await fetch(`/api/sessions/${sessionId}/hardware/${candidate.installation.provider}/install-proposal`, { method: "POST" });
            const proposals = await response.json();
            if (!response.ok) throw new Error(proposals.detail || "Unable to prepare runtime installation");
            elements.empty.hidden = true; elements.result.hidden = false;
            renderActions(proposals);
            elements.actionReview.scrollIntoView({ behavior: "smooth", block: "nearest" });
          } catch (error) { showError(error.message); }
        });
        control = install;
      } else if (candidate.installation) {
        probe.disabled = true;
        probe.textContent = candidate.installation.kind === "driver_guidance"
          ? "Driver guidance"
          : candidate.installation.kind === "runtime_guidance" ? "Runtime guidance" : "Model guidance";
        probe.title = candidate.installation.guidance;
      }
      row.append(label, control); elements.hardwareCandidates.append(row);
    }
    for (const environment of providerEnvironments) {
      const row = document.createElement("div"); row.className = "dependency-row";
      const label = document.createElement("div");
      const name = document.createElement("strong"); name.textContent = `${environment.provider} provider environment`;
      const detail = document.createElement("p"); detail.className = "meta";
      detail.textContent = environment.installed
        ? `${environment.status} · Python ${environment.python_version || "unknown"} · isolated runtime`
        : `not installed · ${environment.environment}`;
      label.append(name, detail);
      const install = document.createElement("button"); install.type = "button"; install.className = "secondary";
      install.textContent = environment.installed && environment.compatible ? "Recheck installed runtime" : "Review runtime install";
      install.addEventListener("click", async () => {
        try {
          await ensureSession();
          const response = await fetch(`/api/sessions/${sessionId}/hardware/${environment.provider}/install-proposal`, { method: "POST" });
          const proposals = await response.json();
          if (!response.ok) throw new Error(proposals.detail || "Unable to prepare runtime installation");
          elements.empty.hidden = true; elements.result.hidden = false;
          renderActions(proposals);
          elements.actionReview.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } catch (error) { showError(error.message); }
      });
      row.append(label, install); elements.hardwareCandidates.append(row);
    }
    if (activeHardwareSection === "leaderboard" && leaderboardHistoryCache.length) renderBenchmarkLeaderboard();
    return candidates;
  } finally { elements.hardwareDetect.disabled = false; }
}

async function restoreCpuBackend() {
  const response = await fetch("/api/hardware/restore-cpu", { method: "POST" });
  if (!response.ok) throw new Error((await response.json()).detail || "Unable to restore CPU mode");
  await loadHardwareStatus();
  elements.hardwareStatus.textContent += " · restart Ollama to activate";
}

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

function formatLeaderboardValue(value, unit = "", digits = 1) {
  return Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "Unavailable";
}

function replaceSelectOptions(select, values, allLabel) {
  const previous = select.value;
  select.replaceChildren();
  const all = document.createElement("option"); all.value = "all"; all.textContent = allLabel; select.append(all);
  for (const value of [...new Set(values.filter(Boolean))].sort()) {
    const option = document.createElement("option"); option.value = value; option.textContent = value; select.append(option);
  }
  select.value = [...select.options].some((option) => option.value === previous) ? previous : "all";
}

function updateLeaderboardFilterOptions() {
  replaceSelectOptions(elements.leaderboardModelFilter, leaderboardHistoryCache.map((item) => item.model), "All models");
  replaceSelectOptions(elements.leaderboardSuiteFilter, leaderboardHistoryCache.map((item) => item.suite), "All suites");
  const historyBackends = leaderboardHistoryCache.flatMap((item) => (item.results || []).map((result) => result.backend || result.runtime));
  replaceSelectOptions(elements.leaderboardBackendFilter, [...leaderboardCandidateCache.map((item) => item.id), ...historyBackends], "All backends");
}

function selectLeaderboardSession(sessionId) {
  const session = leaderboardHistoryCache.find((item) => item.id === sessionId) || leaderboardHistoryCache[0] || null;
  selectedLeaderboardSessionId = session?.id || null;
  selectedLeaderboardRowId = null;
  if (session) {
    elements.leaderboardModelFilter.value = [...elements.leaderboardModelFilter.options].some((option) => option.value === session.model) ? session.model : "all";
    elements.leaderboardSuiteFilter.value = [...elements.leaderboardSuiteFilter.options].some((option) => option.value === session.suite) ? session.suite : "all";
  }
  renderBenchmarkLeaderboard();
}

function createKpi(label, value, detail) {
  const card = document.createElement("div"); card.className = "leaderboard-kpi";
  const name = document.createElement("span"); name.textContent = label;
  const metric = document.createElement("strong"); metric.textContent = value;
  const context = document.createElement("small"); context.className = "meta"; context.textContent = detail;
  card.append(name, metric, context); return card;
}

function renderLeaderboardKpis(rows) {
  elements.leaderboardKpis.replaceChildren();
  const ranked = rows.filter((row) => row.eligible_rank);
  const throughput = ranked.filter((row) => Number.isFinite(row.tokens_per_second)).sort((a, b) => b.tokens_per_second - a.tokens_per_second)[0];
  const ttft = ranked.filter((row) => Number.isFinite(row.ttft_ms)).sort((a, b) => a.ttft_ms - b.ttft_ms)[0];
  const vram = ranked.filter((row) => Number.isFinite(row.peak_vram_mb)).sort((a, b) => a.peak_vram_mb - b.peak_vram_mb)[0];
  const duration = ranked.filter((row) => Number.isFinite(row.average_total_seconds)).sort((a, b) => a.average_total_seconds - b.average_total_seconds)[0];
  const speedup = ranked.filter((row) => Number.isFinite(row.speedup_vs_cpu)).sort((a, b) => b.speedup_vs_cpu - a.speedup_vs_cpu)[0];
  const tested = rows.filter((row) => row.tested);
  const verified = tested.filter((row) => row.probe_verified).length;
  elements.leaderboardKpis.append(
    createKpi("Best throughput", throughput ? formatLeaderboardValue(throughput.tokens_per_second, " tok/s") : "—", throughput?.name || "No ranked result"),
    createKpi("Lowest TTFT", ttft ? formatLeaderboardValue(ttft.ttft_ms, " ms", 0) : "—", ttft?.name || "No TTFT evidence"),
    createKpi("Lowest peak VRAM", vram ? formatLeaderboardValue(vram.peak_vram_mb, " MiB", 0) : "—", vram?.name || "No VRAM evidence"),
    createKpi("Lowest duration", duration ? formatLeaderboardValue(duration.average_total_seconds, " s") : "—", duration?.name || "No duration evidence"),
    createKpi("Best CPU-relative speed", speedup ? formatLeaderboardValue(speedup.speedup_vs_cpu, "×") : "—", speedup?.name || "No CPU baseline evidence"),
    createKpi("Probe verification", tested.length ? `${verified} / ${tested.length}` : "—", "Runtime probe verified results"),
    createKpi("Conforming results", tested.length ? `${ranked.length} / ${tested.length}` : "—", `${rows.filter((row) => row.status === "not_tested").length} detected option(s) not tested`),
  );
}

const LEADERBOARD_METRICS = {
  holistic_capability: ["Holistic capability", "%"],
  tokens_per_second: ["Throughput", " tok/s"],
  ttft_ms: ["TTFT", " ms"],
  average_total_seconds: ["Total time", " s"],
  peak_vram_mb: ["Peak VRAM", " MiB"],
  speedup_vs_cpu: ["CPU-relative speed", "×"],
  performance_index: ["Performance index", ""],
  integrity_overall: ["Integrity & comprehension", "%"],
  combined_score: ["Combined quality + performance", ""],
};

function renderLeaderboardMetricComparison(rows) {
  const metric = elements.leaderboardMetric.value;
  const [label, unit] = LEADERBOARD_METRICS[metric] || [metric, ""];
  const metricValue = (row) => metric === "holistic_capability" ? row.integrity_overall : row[metric];
  const values = rows.map(metricValue).filter(Number.isFinite);
  const maximum = Math.max(...values, 0);
  const comparison = document.createElement("div"); comparison.className = "leaderboard-metric-comparison";
  const heading = document.createElement("strong"); heading.textContent = `${label} by backend`; comparison.append(heading);
  for (const row of rows) {
    const item = document.createElement("button"); item.type = "button"; item.className = "leaderboard-metric-row";
    const name = document.createElement("span"); name.textContent = row.name;
    const value = document.createElement("span"); value.textContent = formatLeaderboardValue(metricValue(row), unit);
    const bar = document.createElement("span"); bar.className = "leaderboard-metric-bar";
    bar.style.setProperty("--metric-width", Number.isFinite(metricValue(row)) && maximum ? `${Math.max(3, metricValue(row) / maximum * 100)}%` : "0%");
    item.setAttribute("aria-label", `${row.name}: ${value.textContent}; ${row.status === "not_tested" ? "not tested" : row.status}`);
    item.addEventListener("click", () => { selectedLeaderboardRowId = row.id; renderBenchmarkLeaderboard(); });
    item.append(name, value, bar); comparison.append(item);
  }
  elements.leaderboardBackendChart.append(comparison);
}

function svgNode(name, attributes = {}) {
  const node = document.createElementNS(SVG_NAMESPACE, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function resetChart(figure, title) {
  figure.replaceChildren();
  const caption = document.createElement("figcaption"); caption.textContent = title; figure.append(caption);
}

function renderLeaderboardScatter(rows) {
  resetChart(elements.leaderboardBackendChart, "Throughput versus responsiveness");
  const eligible = rows.filter((row) => row.eligible_rank && Number.isFinite(row.tokens_per_second) && Number.isFinite(row.ttft_ms));
  if (!eligible.length) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No comparable TTFT and throughput evidence is available."; elements.leaderboardBackendChart.append(empty); renderLeaderboardMetricComparison(rows); return;
  }
  const points = window.JSONCodrLeaderboard.scalePoints(eligible.map((row) => ({ x: row.ttft_ms, y: row.tokens_per_second, row })), { width: 520, height: 240, padding: 34 });
  const svg = svgNode("svg", { viewBox: "0 0 520 240", role: "img", "aria-label": "Higher and farther left indicates faster output and lower time to first token" });
  for (const y of [34, 90, 146, 206]) svg.append(svgNode("line", { x1: 34, y1: y, x2: 486, y2: y, class: "chart-grid" }));
  const xLabel = svgNode("text", { x: 414, y: 232, class: "chart-label" }); xLabel.textContent = "TTFT (ms)"; svg.append(xLabel);
  const yLabel = svgNode("text", { x: 4, y: 16, class: "chart-label" }); yLabel.textContent = "tokens/s"; svg.append(yLabel);
  for (const point of points) {
    const circle = svgNode("circle", { cx: point.cx, cy: point.cy, r: 8, class: "chart-point", role: "button" });
    circle.setAttribute("tabindex", "0");
    circle.setAttribute("aria-label", `${point.row.name}: ${point.row.tokens_per_second.toFixed(2)} tokens per second, ${point.row.ttft_ms.toFixed(1)} milliseconds TTFT`);
    const title = svgNode("title"); title.textContent = circle.getAttribute("aria-label"); circle.append(title);
    const choose = () => { selectedLeaderboardRowId = point.row.id; renderBenchmarkLeaderboard(); };
    circle.addEventListener("click", choose);
    circle.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } });
    svg.append(circle);
  }
  elements.leaderboardBackendChart.append(svg);
  const summary = document.createElement("p"); summary.className = "meta"; summary.textContent = eligible.map((row) => `${row.name}: ${row.tokens_per_second.toFixed(2)} tok/s at ${row.ttft_ms.toFixed(1)} ms`).join("; "); elements.leaderboardBackendChart.append(summary);
  if (eligible.length === 1) {
    const note = document.createElement("p"); note.className = "meta"; note.textContent = "Only one comparable result is available; at least two are required for comparison."; elements.leaderboardBackendChart.append(note);
  }
  renderLeaderboardMetricComparison(rows);
}

function renderLeaderboardTrend(row) {
  resetChart(elements.leaderboardTrendChart, "Performance history");
  if (!row || !row.tested) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "Select a tested backend to view its history."; elements.leaderboardTrendChart.append(empty); return;
  }
  const metric = elements.leaderboardMetric.value;
  const [metricLabel, metricUnit] = LEADERBOARD_METRICS[metric] || [metric, ""];
  if (metric === "holistic_capability" || metric === "integrity_overall" || metric === "combined_score") {
    const note = document.createElement("p"); note.className = "meta";
    note.textContent = "Quality ranks use the latest strict v2 integrity evaluation. Review its per-scenario history in Performance benchmarks.";
    elements.leaderboardTrendChart.append(note); return;
  }
  const trend = window.JSONCodrLeaderboard.buildTrend(leaderboardHistoryCache, row, metric);
  const validTrend = trend.filter((point) => point.eligible && Number.isFinite(point.value));
  if (validTrend.length < 2) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = validTrend.length ? `One valid matching run is available (${formatLeaderboardValue(validTrend[0].value, metricUnit)}); run it again to establish a trend.` : "No valid matching historical runs are available."; elements.leaderboardTrendChart.append(empty); return;
  }
  const points = window.JSONCodrLeaderboard.scalePoints(validTrend.map((point) => ({ x: trend.indexOf(point), y: point.value, point })), { width: 520, height: 240, padding: 34 });
  const pointsBySession = new Map(points.map((point) => [point.point.session_id, point]));
  const svg = svgNode("svg", { viewBox: "0 0 520 240", role: "img", "aria-label": `${row.name} ${metricLabel} over time` });
  for (const y of [34, 90, 146, 206]) svg.append(svgNode("line", { x1: 34, y1: y, x2: 486, y2: y, class: "chart-grid" }));
  const xLabel = svgNode("text", { x: 430, y: 232, class: "chart-label" }); xLabel.textContent = "Run"; svg.append(xLabel);
  const yLabel = svgNode("text", { x: 4, y: 16, class: "chart-label" }); yLabel.textContent = metricLabel; svg.append(yLabel);
  let segment = [];
  const appendSegment = () => { if (segment.length > 1) svg.append(svgNode("polyline", { points: segment.map((point) => `${point.cx},${point.cy}`).join(" "), fill: "none", stroke: "currentColor", "stroke-width": 3 })); segment = []; };
  for (const trendPoint of trend) { const point = pointsBySession.get(trendPoint.session_id); if (point) segment.push(point); else appendSegment(); }
  appendSegment();
  for (const point of points) {
    const circle = svgNode("circle", { cx: point.cx, cy: point.cy, r: 6, class: "chart-point", role: "img" });
    circle.setAttribute("tabindex", "0"); circle.setAttribute("aria-label", `${new Date(point.point.created_at).toLocaleDateString()}: ${point.point.value.toFixed(2)}${metricUnit} ${metricLabel}`); svg.append(circle);
    const title = svgNode("title"); title.textContent = circle.getAttribute("aria-label"); circle.append(title);
  }
  elements.leaderboardTrendChart.append(svg);
  const summary = document.createElement("p"); summary.className = "meta"; summary.textContent = `${metricLabel}: ${trend.map((point) => `${new Date(point.created_at).toLocaleDateString()}: ${point.eligible ? `${point.value.toFixed(2)}${metricUnit}` : "invalid / unavailable gap"}`).join("; ")}`; elements.leaderboardTrendChart.append(summary);
}

function handoffUntestedBackend(row) {
  if (!row.runnable || !row.compatible) { elements.leaderboardStatus.textContent = row.availability_reason || "This backend is not currently runnable."; return false; }
  const modelOption = [...elements.hardwareBenchmarkModel.options].find((option) => option.value === row.model && !option.disabled);
  if (!modelOption) { elements.leaderboardStatus.textContent = `Benchmark model ${row.model} is not available in the benchmark runner.`; return false; }
  const suiteOption = [...elements.hardwareBenchmarkSuite.options].find((option) => option.value === row.suite && !option.disabled);
  if (!suiteOption) { elements.leaderboardStatus.textContent = `Benchmark suite ${row.suite} is not available in the benchmark runner.`; return false; }
  const backendOption = [...elements.hardwareBenchmarkBackend.options].find((option) => option.value === row.backend && !option.disabled);
  if (!backendOption) { elements.leaderboardStatus.textContent = `Backend ${row.backend} is not available in the benchmark runner.`; return false; }
  elements.hardwareBenchmarkModel.value = row.model;
  elements.hardwareBenchmarkSuite.value = row.suite;
  elements.hardwareBenchmarkBackend.value = row.backend;
  selectHardwareSection("benchmarks");
  return true;
}

function renderLeaderboardDetails(row) {
  elements.leaderboardDetails.replaceChildren();
  if (!row) { const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No result matches the current filters."; elements.leaderboardDetails.append(empty); return; }
  selectedLocalperfEvaluationId = row.evaluation_id;
  elements.localperfExport.disabled = !selectedLocalperfEvaluationId;
  const heading = document.createElement("h4"); heading.textContent = `${row.model} · ${row.name}`;
  const conformanceLabel = row.conforming === true ? "valid" : row.conforming === false ? "invalid" : "unknown";
  const description = document.createElement("p"); description.className = "meta"; description.textContent = `${row.suite} · ${row.workload_version} · ${row.status}${row.probe_verified ? " · runtime probe verified" : " · runtime probe unverified"} · Conformance: ${conformanceLabel}`;
  elements.leaderboardDetails.append(heading, description);
  if (row.status === "not_tested") {
    const action = document.createElement("button"); action.type = "button"; action.className = "primary"; action.textContent = "Test this backend"; action.addEventListener("click", () => handoffUntestedBackend(row)); elements.leaderboardDetails.append(action); return;
  }
  if (row.availability_reason) { const reason = document.createElement("p"); reason.className = "meta"; reason.textContent = row.availability_reason; elements.leaderboardDetails.append(reason); }
  const metrics = document.createElement("p"); metrics.textContent = `Performance index ${formatLeaderboardValue(row.performance_index, "", 0)} · ${formatLeaderboardValue(row.tokens_per_second, " tok/s")} · ${formatLeaderboardValue(row.ttft_ms, " ms")} TTFT · ${formatLeaderboardValue(row.peak_vram_mb, " MiB", 0)} peak VRAM`; elements.leaderboardDetails.append(metrics);
  const quality = document.createElement("p"); quality.textContent = row.integrity_overall == null
    ? "Integrity evaluation unavailable for this model."
    : `Integrity ${formatLeaderboardValue(row.integrity_score, "%", 1)} · Comprehension ${formatLeaderboardValue(row.comprehension_score, "%", 1)} · Overall ${formatLeaderboardValue(row.integrity_overall, "%", 1)} · Combined ${formatLeaderboardValue(row.combined_score, "", 1)}`;
  elements.leaderboardDetails.append(quality);
  const metricNames = [["tokens_per_second", "Throughput"], ["ttft_ms", "TTFT"], ["total_seconds", "Duration"], ["peak_vram_mb", "Peak VRAM"]];
  const stats = document.createElement("ul");
  for (const [key, label] of metricNames) {
    const values = row.tests.map((sample) => sample[key]); const summary = window.JSONCodrLeaderboard.percentiles(values);
    const item = document.createElement("li"); item.textContent = `${label}: p50 ${formatLeaderboardValue(summary.p50)}, p90 ${formatLeaderboardValue(summary.p90)}, min ${formatLeaderboardValue(summary.min)}, max ${formatLeaderboardValue(summary.max)}`; stats.append(item);
  }
  elements.leaderboardDetails.append(stats);
  const metadata = document.createElement("p"); metadata.className = "meta"; metadata.textContent = `Session ${row.session_id} · backend ${row.backend} · runtime ${row.runtime || "unavailable"} · kind ${row.kind || "unavailable"} · active ${row.active == null ? "unknown" : row.active ? "yes" : "no"} · evaluation ${row.evaluation_id || "unavailable"} · configuration hash ${row.configuration_hash || "unavailable"} · workload hash ${row.workload_hash || "unavailable"}`; elements.leaderboardDetails.append(metadata);
  if (row.runtime_metadata) { const runtime = document.createElement("p"); runtime.className = "meta"; runtime.textContent = `Runtime metadata: ${JSON.stringify(row.runtime_metadata)}`; elements.leaderboardDetails.append(runtime); }
  const validityReasons = [...(row.rejection_reasons || []), ...(row.conformance_reasons || []), ...(row.compatibility_reasons || []), row.quarantine_reason].filter(Boolean);
  if (row.error || validityReasons.length) { const warning = document.createElement("p"); warning.className = "error"; warning.textContent = row.error || validityReasons.join("; "); elements.leaderboardDetails.append(warning); }
  const samples = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = `Show ${row.tests.length} per-prompt samples`; samples.append(summary);
  for (const sample of row.tests) { const line = document.createElement("p"); line.className = "meta"; line.textContent = `${sample.prompt_id || sample.test || "sample"} #${sample.repetition || 1}: ${formatLeaderboardValue(sample.tokens_per_second, " tok/s")} · ${formatLeaderboardValue(sample.ttft_ms, " ms")} TTFT · ${formatLeaderboardValue(sample.total_seconds, " s")} total`; samples.append(line); }
  elements.leaderboardDetails.append(samples);
}

function renderBenchmarkLeaderboard() {
  if (!leaderboardHistoryCache.length && !integrityHistoryCache.length) {
    elements.leaderboardTable.replaceChildren(); const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 11; cell.className = "meta"; cell.textContent = "No benchmark history. Run Performance benchmarks first."; row.append(cell); elements.leaderboardTable.append(row);
    elements.leaderboardKpis.replaceChildren(); elements.leaderboardStatus.textContent = "No saved benchmark results."; renderLeaderboardScatter([]); renderLeaderboardTrend(null); renderLeaderboardDetails(null); return;
  }
  const allRows = window.JSONCodrLeaderboard.joinIntegrity(window.JSONCodrLeaderboard.buildAllRows(leaderboardHistoryCache), integrityHistoryCache);
  const rankedRows = window.JSONCodrLeaderboard.filterAndRank(allRows, {
    search: elements.leaderboardSearch.value,
    model: elements.leaderboardModelFilter.value,
    backend: elements.leaderboardBackendFilter.value,
    suite: elements.leaderboardSuiteFilter.value,
    metric: elements.leaderboardMetric.value,
  });
  const rows = window.JSONCodrLeaderboard.sortRows(rankedRows, leaderboardSort);
  const selected = window.JSONCodrLeaderboard.selectRow(rows, selectedLeaderboardRowId); selectedLeaderboardRowId = selected?.id || null;
  elements.leaderboardStatus.textContent = `${rows.length} non-failed result(s) · sorted by ${leaderboardSort.key.replaceAll("_", " ")}`;
  for (const button of elements.leaderboardSortButtons) {
    if (button.dataset.sortKey === leaderboardSort.key) button.setAttribute("aria-sort", leaderboardSort.direction === "asc" ? "ascending" : "descending");
    else button.removeAttribute("aria-sort");
  }
  renderLeaderboardKpis(rows); elements.leaderboardTable.replaceChildren();
  for (const row of rows) {
    const tableRow = document.createElement("tr"); tableRow.tabIndex = 0; tableRow.classList.toggle("is-selected", row.id === selectedLeaderboardRowId);
    const evidenceStatus = row.status === "not_tested" ? "Not tested" : row.status === "completed" && row.conforming === true ? "Conforming" : row.status === "completed" && row.conforming === false ? "Nonconforming" : row.status === "completed" ? "Unverified evidence" : row.status;
    const values = [row.rank || "—", `${row.model} · ${row.name}`, formatLeaderboardValue(row.performance_index, "", 0), formatLeaderboardValue(row.integrity_overall, "%", 1), formatLeaderboardValue(row.combined_score, "", 1), formatLeaderboardValue(row.tokens_per_second), formatLeaderboardValue(row.ttft_ms, " ms", 0), formatLeaderboardValue(row.average_total_seconds, " s"), formatLeaderboardValue(row.peak_vram_mb, " MiB", 0), formatLeaderboardValue(row.speedup_vs_cpu, "×"), evidenceStatus];
    for (const value of values) { const cell = document.createElement("td"); cell.textContent = value; tableRow.append(cell); }
    const choose = () => { selectedLeaderboardRowId = row.id; renderBenchmarkLeaderboard(); };
    tableRow.addEventListener("click", choose); tableRow.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } }); elements.leaderboardTable.append(tableRow);
  }
  renderLeaderboardScatter(rows); renderLeaderboardTrend(selected); renderLeaderboardDetails(selected);
}

async function loadBenchmarkLeaderboard() {
  elements.leaderboardStatus.textContent = "Loading benchmark comparisons…";
  const historyPromise = loadBenchmarkHistory();
  const candidatesPromise = leaderboardCandidateCache.length ? Promise.resolve(leaderboardCandidateCache) : detectHardware();
  await Promise.all([historyPromise, candidatesPromise, loadIntegrityBenchmarkHistory()]); updateLeaderboardFilterOptions(); renderBenchmarkLeaderboard();
}

function renderBenchmarkResults(benchmark) {
  elements.hardwareBenchmarkResults.replaceChildren();
  selectedLocalperfEvaluationId = null;
  for (const result of benchmark.results) {
    const row = document.createElement("div"); row.className = "dependency-row";
    const label = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = result.name;
    const metrics = document.createElement("p"); metrics.className = "meta";
    let components = null;
    if (result.status === "completed") {
      const relative = result.speedup_vs_cpu == null ? "CPU baseline unavailable" : `${result.speedup_vs_cpu.toFixed(2)}× CPU`;
      const gpu = result.gpu_percent > 0
        ? ` · ${result.gpu_percent}% GPU · ${(result.vram_bytes / 1048576).toFixed(0)} MiB VRAM`
        : "";
      const eligibility = result.selected
        ? " · Selected for compatibility and performance"
        : result.eligible ? " · Eligible" : ` · Not eligible: ${(result.rejection_reasons || []).join("; ")}`;
      metrics.textContent = `${result.tokens_per_second.toFixed(2)} tokens/s · ${result.average_total_seconds.toFixed(3)}s average · ${relative}${gpu}${eligibility}`;
      if (result.localperf) {
        if (!selectedLocalperfEvaluationId) selectedLocalperfEvaluationId = result.localperf.evaluation_id;
        const conformance = result.localperf.conformance.conforming ? "conforming" : `non-conforming: ${result.localperf.conformance.reasons.join(", ")}`;
        metrics.textContent += ` · LocalPerf ${conformance}`;
      }
      components = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${result.runtime} · ${result.kind} · ${result.verified ? "verified" : "not yet verified"}${result.active ? " · active" : ""}`;
      components.append(summary);
      for (const test of result.tests) {
        const line = document.createElement("p"); line.className = "meta";
        line.textContent = `${test.prompt_id || test.test} · ${test.test} #${test.repetition}: ${test.total_seconds.toFixed(3)}s · ${test.ttft_ms == null ? "TTFT unavailable" : `${test.ttft_ms.toFixed(1)} ms TTFT`} · ${test.peak_vram_mb == null ? "VRAM unavailable" : `${test.peak_vram_mb.toFixed(1)} MiB peak VRAM`} · ${test.tokens_per_second.toFixed(2)} tokens/s`;
        components.append(line);
      }
    } else {
      metrics.textContent = `${result.status}: ${result.error || "Backend is unavailable"}`;
    }
    label.append(name, metrics);
    if (components) label.append(components);
    row.append(label); elements.hardwareBenchmarkResults.append(row);
  }
  elements.localperfExport.disabled = !selectedLocalperfEvaluationId;
}

async function loadBenchmarkHistory() {
  const response = await fetch("/api/hardware/benchmarks");
  if (!response.ok) throw new Error("Unable to load benchmark history");
  const history = await response.json();
  leaderboardHistoryCache = history;
  if (!history.some((benchmark) => benchmark.id === selectedLeaderboardSessionId)) selectedLeaderboardSessionId = history[0]?.id || null;
  elements.hardwareBenchmarkHistory.replaceChildren();
  if (!history.length) {
    elements.hardwareBenchmarkHistory.innerHTML = '<p class="meta">No benchmark history.</p>';
    return;
  }
  for (const benchmark of history) {
    const button = document.createElement("button"); button.type = "button"; button.className = "secondary";
    button.textContent = `${benchmark.suite} · ${benchmark.model} · ${new Date(benchmark.created_at).toLocaleString()}`;
    button.addEventListener("click", () => { renderBenchmarkResults(benchmark); selectLeaderboardSession(benchmark.id); });
    elements.hardwareBenchmarkHistory.append(button);
  }
  renderBenchmarkResults(history[0]);
  if (activeHardwareSection === "leaderboard") { updateLeaderboardFilterOptions(); renderBenchmarkLeaderboard(); }
  return history;
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
    selectedLeaderboardSessionId = benchmark.id;
    await loadBenchmarkHistory();
    elements.hardwareBenchmarkStatus.textContent = `Benchmark complete · selected ${benchmark.model} on ${benchmark.selected_backend}`;
  } finally {
    elements.hardwareBenchmarkRun.disabled = false;
  }
}

async function clearHardwareBenchmarks() {
  elements.hardwareBenchmarkClear.disabled = true;
  try {
    const response = await fetch("/api/hardware/benchmarks", { method: "DELETE" });
    if (!response.ok) throw new Error("Unable to clear benchmark data");
    await loadBenchmarkHistory();
    selectedLeaderboardSessionId = null;
    selectedLeaderboardRowId = null;
    renderBenchmarkLeaderboard();
    elements.hardwareBenchmarkResults.innerHTML = '<p class="meta">No benchmark selected.</p>';
    elements.hardwareBenchmarkStatus.textContent = "Previous benchmark data cleared.";
  } finally {
    elements.hardwareBenchmarkClear.disabled = false;
  }
}

function renderIntegrityBenchmark(benchmark) {
  elements.integrityBenchmarkScores.replaceChildren();
  elements.integrityBenchmarkResults.replaceChildren();
  if (!benchmark?.scores || !Array.isArray(benchmark.scenarios)) {
    elements.integrityBenchmarkResults.innerHTML = '<p class="meta">This saved evaluation is incomplete and cannot be displayed.</p>';
    return;
  }
  const metadata = document.createElement("p");
  metadata.className = "meta";
  metadata.textContent = `${benchmark.suite_version || "Unknown suite"} · schema ${benchmark.schema_version || "unknown"} · ${benchmark.status || "unknown"} · ${benchmark.created_at ? new Date(benchmark.created_at).toLocaleString() : "unknown time"}`;
  elements.integrityBenchmarkResults.append(metadata);
  for (const [label, value] of [
    ["Integrity", benchmark.scores.integrity],
    ["Comprehension", benchmark.scores.comprehension],
    ["Overall", benchmark.scores.overall],
  ]) {
    const card = document.createElement("article");
    const caption = document.createElement("span");
    caption.className = "meta";
    caption.textContent = label;
    const score = document.createElement("strong");
    score.textContent = `${Number(value).toFixed(1)}%`;
    card.append(caption, score);
    elements.integrityBenchmarkScores.append(card);
  }
  for (const scenario of benchmark.scenarios) {
    const details = document.createElement("details");
    details.className = "dependency-row";
    const summary = document.createElement("summary");
    summary.textContent = `${scenario.passed ? "PASS" : "REVIEW"} · ${scenario.name} · ${Number(scenario.score).toFixed(1)}%`;
    details.append(summary);
    for (const evidence of (Array.isArray(scenario.evidence) ? scenario.evidence : []).filter((item) => item && typeof item === "object")) {
      const line = document.createElement("p");
      line.className = "meta integrity-evidence";
      line.textContent = `Run ${evidence.repetition} · ${evidence.passed ? "pass" : "fail"} · ${evidence.evaluation_reason || "unclassified"} · ${evidence.error || evidence.output || "No output"}${evidence.truncated ? ` · truncated from ${evidence.output_length} characters` : ""}`;
      details.append(line);
    }
    elements.integrityBenchmarkResults.append(details);
  }
}

async function loadIntegrityBenchmarkHistory() {
  const response = await fetch("/api/integrity-benchmarks");
  if (!response.ok) throw new Error("Unable to load integrity benchmark history");
  const payload = await response.json();
  const history = Array.isArray(payload) ? payload.filter((benchmark) => benchmark?.scores && Array.isArray(benchmark.scenarios)) : [];
  integrityHistoryCache = history;
  elements.integrityBenchmarkHistory.replaceChildren();
  if (!history.length) {
    elements.integrityBenchmarkHistory.innerHTML = '<p class="meta">No integrity evaluation history.</p>';
    return history;
  }
  for (const benchmark of history) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = `${benchmark.suite} · ${benchmark.model} · ${Number(benchmark.scores.overall).toFixed(1)}% · ${new Date(benchmark.created_at).toLocaleString()}`;
    button.addEventListener("click", () => renderIntegrityBenchmark(benchmark));
    elements.integrityBenchmarkHistory.append(button);
  }
  renderIntegrityBenchmark(history[0]);
  return history;
}

async function runIntegrityBenchmark() {
  elements.integrityBenchmarkRun.disabled = true;
  elements.integrityBenchmarkStatus.textContent = "Running integrity and comprehension evaluation…";
  try {
    const response = await fetch("/api/integrity-benchmarks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        suite: elements.integrityBenchmarkSuite.value,
        model: elements.integrityBenchmarkModel.value,
      }),
    });
    const benchmark = await response.json();
    if (!response.ok) throw new Error(benchmark.detail || "Integrity evaluation failed");
    renderIntegrityBenchmark(benchmark);
    await loadIntegrityBenchmarkHistory();
    elements.integrityBenchmarkStatus.textContent = `Evaluation complete · ${Number(benchmark.scores.overall).toFixed(1)}% overall`;
  } finally {
    elements.integrityBenchmarkRun.disabled = false;
  }
}

function exportLocalperfPackage() {
  if (!selectedLocalperfEvaluationId) return;
  const details = elements.localperfIncludeDetails.checked ? "true" : "false";
  window.location.assign(`/api/localperf/packages/${encodeURIComponent(selectedLocalperfEvaluationId)}?include_system_details=${details}`);
}

async function previewLocalperfPackage(file) {
  pendingLocalperfPackage = await file.arrayBuffer();
  const response = await fetch("/api/localperf/packages/preview", {
    method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: pendingLocalperfPackage,
  });
  const preview = await response.json();
  if (!response.ok) throw new Error(preview.detail || "Package validation failed");
  elements.localperfRetainDetails.disabled = !preview.contains_system_details;
  elements.localperfRetainDetails.checked = false;
  elements.localperfImport.disabled = false;
  elements.localperfPackageStatus.textContent = preview.contains_system_details
    ? "Valid package contains system details. Consent is required to retain them."
    : "Valid sanitized package. Ready to import.";
}

async function importLocalperfPackage() {
  if (!pendingLocalperfPackage) return;
  const retain = elements.localperfRetainDetails.checked ? "true" : "false";
  const response = await fetch(`/api/localperf/packages/import?retain_system_details=${retain}`, {
    method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: pendingLocalperfPackage,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Package import failed");
  elements.localperfPackageStatus.textContent = `Imported reference package ${result.package_id.slice(0, 12)} · local baseline disabled.`;
  elements.localperfImport.disabled = true;
}

async function searchOptimizedModels() {
  elements.optimizedModelSearchRun.disabled = true;
  elements.optimizedModelSearchResults.innerHTML = '<p class="meta">Searching approved remote sources…</p>';
  try {
    const provider = encodeURIComponent(elements.optimizedModelSearchProvider.value);
    const query = encodeURIComponent(elements.optimizedModelSearchQuery.value || "coder");
    const response = await fetch(`/api/inference/models/search?provider=${provider}&q=${query}&limit=10`);
    const models = await response.json();
    if (!response.ok) throw new Error(models.detail || "Optimized-model search failed");
    elements.optimizedModelSearchResults.replaceChildren();
    if (!models.length) elements.optimizedModelSearchResults.innerHTML = '<p class="meta">No compatible candidates found.</p>';
    for (const model of models) {
      const row = document.createElement("div"); row.className = "dependency-row";
      const label = document.createElement("div");
      const name = document.createElement("strong"); name.textContent = model.repository;
      const detail = document.createElement("p"); detail.className = "meta";
      detail.textContent = `${model.provider} · ${model.device} · ${model.format} · ${model.license} · ${model.source}`;
      const link = document.createElement("a"); link.className = "secondary file-button"; link.href = model.source_url;
      link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "Review download source";
      label.append(name, detail); row.append(label, link); elements.optimizedModelSearchResults.append(row);
    }
  } finally { elements.optimizedModelSearchRun.disabled = false; }
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
      selectDestination("terminal");
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
      if (model.installed) {
        elements.hardwareBenchmarkModel.append(option.cloneNode(true));
        elements.integrityBenchmarkModel.append(option.cloneNode(true));
      }
    }
    const installed = models.filter((model) => model.installed).length;
    elements.modelCount.textContent = `${installed} of ${models.length} installed`;
    elements.model.disabled = installed === 0;
    elements.submit.disabled = installed === 0;
    updateModelDetail();
    renderGpuProfileControls();
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
  const { proposal, phrase, approveButton } = pendingDestructiveAction;
  const enteredPhrase = elements.destructiveInput.value.trim().toUpperCase();
  if (enteredPhrase !== phrase) return showError("Confirmation code does not match");
  const response = await fetch(`/api/sessions/${sessionId}/action-proposals/${proposal.id}/confirm-destructive`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-JSON-CODR": "1" },
    body: JSON.stringify({ terminal_id: terminalId, phrase: enteredPhrase }),
  });
  const approval = await response.json();
  if (!response.ok) return showError(approval.detail || "Unable to confirm destructive action");
  pendingDestructiveAction = null;
  elements.destructiveDialog.close();
  try {
    await sendApprovedAction(proposal, approval.token, approveButton);
  } catch (error) {
    showError(error.message);
  }
});
elements.destructiveDialog.addEventListener("close", () => {
  if (!pendingDestructiveAction) return;
  const { approveButton } = pendingDestructiveAction;
  approveButton.disabled = false;
  approveButton.textContent = "Approve and run";
  pendingDestructiveAction = null;
});
for (const button of elements.navigationButtons) {
  button.addEventListener("click", () => selectDestination(button.dataset.destination));
}
for (const button of elements.hardwareSectionButtons) {
  button.addEventListener("click", () => selectHardwareSection(button.dataset.hardwareSection));
}
elements.sidebarCollapse.addEventListener("click", () => {
  setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
});
elements.mobileNavigationToggle.addEventListener("click", () => {
  if (document.body.classList.contains("navigation-open")) closeNavigationDrawer({ restoreFocus: true });
  else openNavigationDrawer();
});
elements.navigationBackdrop.addEventListener("click", () => closeNavigationDrawer({ restoreFocus: true }));
elements.sidebarResizeHandle.addEventListener("pointerdown", (event) => {
  if (narrowNavigationQuery.matches) return;
  event.preventDefault();
  let pendingWidth = sidebarWidth;
  let resizeFrame = null;
  const renderResize = () => { resizeFrame = null; applySidebarWidth(pendingWidth); };
  const onPointerMove = (moveEvent) => {
    pendingWidth = boundedSidebarWidth(moveEvent.clientX);
    if (resizeFrame === null) resizeFrame = requestAnimationFrame(renderResize);
  };
  const onPointerUp = () => {
    window.removeEventListener("pointermove", onPointerMove);
    if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
    const width = applySidebarWidth(pendingWidth);
    navigationChangeRevision += 1;
    saveSettings({ ui: { sidebar_width: width } }).catch((error) => showError(error.message));
  };
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
});
elements.sidebarResizeHandle.addEventListener("keydown", (event) => {
  const key = event.key;
  const delta = key === "ArrowLeft" ? -10 : key === "ArrowRight" ? 10 : 0;
  if (!delta) return;
  event.preventDefault();
  const width = applySidebarWidth(sidebarWidth + delta);
  navigationChangeRevision += 1;
  saveSettings({ ui: { sidebar_width: width } }).catch((error) => showError(error.message));
});
narrowNavigationQuery.addEventListener("change", () => closeNavigationDrawer());
elements.hardwareDetect.addEventListener("click", () => detectHardware().catch((error) => showError(error.message)));
elements.hardwareRestoreCpu.addEventListener("click", () => restoreCpuBackend().catch((error) => showError(error.message)));
elements.hardwareBenchmarkRun.addEventListener("click", () => runHardwareBenchmark().catch((error) => {
  elements.hardwareBenchmarkStatus.textContent = error.message;
  showError(error.message);
}));
elements.hardwareBenchmarkClear.addEventListener("click", () => clearHardwareBenchmarks().catch((error) => {
  elements.hardwareBenchmarkStatus.textContent = error.message;
}));
elements.integrityBenchmarkRun.addEventListener("click", () => runIntegrityBenchmark().catch((error) => {
  elements.integrityBenchmarkStatus.textContent = error.message;
  showError(error.message);
}));
elements.leaderboardSearch.addEventListener("input", renderBenchmarkLeaderboard);
elements.leaderboardBackendFilter.addEventListener("change", renderBenchmarkLeaderboard);
elements.leaderboardMetric.addEventListener("change", renderBenchmarkLeaderboard);
for (const button of elements.leaderboardSortButtons) {
  button.addEventListener("click", () => {
    const key = button.dataset.sortKey;
    leaderboardSort = leaderboardSort.key === key
      ? { key, direction: leaderboardSort.direction === "asc" ? "desc" : "asc" }
      : { key, direction: key === "rank" ? "asc" : "desc" };
    renderBenchmarkLeaderboard();
  });
}
elements.leaderboardModelFilter.addEventListener("change", () => {
  const model = elements.leaderboardModelFilter.value;
  const suite = elements.leaderboardSuiteFilter.value;
  const session = window.JSONCodrLeaderboard.chooseSession(leaderboardHistoryCache, selectedLeaderboardSessionId, model, suite);
  if (session) { selectedLeaderboardSessionId = session.id; selectedLeaderboardRowId = null; }
  renderBenchmarkLeaderboard();
});
elements.leaderboardSuiteFilter.addEventListener("change", () => {
  const model = elements.leaderboardModelFilter.value;
  const suite = elements.leaderboardSuiteFilter.value;
  const session = window.JSONCodrLeaderboard.chooseSession(leaderboardHistoryCache, selectedLeaderboardSessionId, model, suite);
  if (session) { selectedLeaderboardSessionId = session.id; selectedLeaderboardRowId = null; }
  renderBenchmarkLeaderboard();
});
elements.localperfExport.addEventListener("click", exportLocalperfPackage);
elements.localperfImportInput.addEventListener("change", () => {
  const file = elements.localperfImportInput.files[0];
  if (file) previewLocalperfPackage(file).catch((error) => { elements.localperfPackageStatus.textContent = error.message; });
});
elements.localperfImport.addEventListener("click", () => importLocalperfPackage().catch((error) => {
  elements.localperfPackageStatus.textContent = error.message;
}));
elements.optimizedModelSearchRun.addEventListener("click", () => searchOptimizedModels().catch((error) => {
  elements.optimizedModelSearchResults.innerHTML = `<p class="meta">${escapeHtml(error.message)}</p>`;
}));
elements.hardwareProfileModel.addEventListener("change", renderGpuProfileControls);
elements.hardwareProfileMode.addEventListener("change", () => {
  elements.hardwareProfileAdvanced.hidden = elements.hardwareProfileMode.value !== "advanced";
});
elements.hardwareProfileSave.addEventListener("click", () => saveGpuProfile().catch((error) => {
  elements.hardwareProfileStatus.textContent = error.message;
  showError(error.message);
}));
elements.hardwareProfileReset.addEventListener("click", () => saveGpuProfile(true).catch((error) => {
  elements.hardwareProfileStatus.textContent = error.message;
  showError(error.message);
}));
elements.settingSkillsOpen.addEventListener("change", () => {
  skillsChangeRevision += 1;
  const open = elements.settingSkillsOpen.checked;
  selectDestination(open ? "skills" : "chat");
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
    selectDestination("skills");
    elements.settingSkillsOpen.checked = true;
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
    selectDestination("terminal");
  }
  if (event.ctrlKey && event.altKey && event.key.toLowerCase() === "b") {
    event.preventDefault();
    selectDestination("context");
  }
  if (event.key === "Escape" && document.body.classList.contains("navigation-open")) {
    closeNavigationDrawer({ restoreFocus: true });
  }
});

loadApplication().then(() => queueSettingsLoad()).catch((error) => showError(error.message));
loadHardwareStatus().catch((error) => showError(error.message));
loadAttachments().catch((error) => showError(error.message));
loadSkillsets().catch((error) => showError(error.message));
