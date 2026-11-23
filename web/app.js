const elements = {
  form: document.querySelector("#chat-form"),
  health: document.querySelector("#health-status"),
  model: document.querySelector("#model-select"),
  workspaceAgentSelect: document.querySelector("#workspace-agent-select"),
  modelCount: document.querySelector("#model-count"),
  modelDetail: document.querySelector("#model-detail"),
  prompt: document.querySelector("#prompt-input"),
  submit: document.querySelector("#submit-button"),
  cancel: document.querySelector("#cancel-button"),
  requestStatus: document.querySelector("#request-status"),
  workspaceAttach: document.querySelector("#workspace-attach"),
  workspaceAttachmentMenu: document.querySelector("#workspace-attachment-menu"),
  workspaceFilesPopover: document.querySelector("#workspace-files-popover"),
  workspaceFilesPopoverList: document.querySelector("#workspace-files-popover-list"),
  workspaceFilesManage: document.querySelector("#workspace-files-manage"),
  responseModel: document.querySelector("#response-model"),
  empty: document.querySelector("#empty-state"),
  result: document.querySelector("#result-state"),
  summary: document.querySelector("#summary-output"),
  content: document.querySelector("#content-output"),
  artifactOutput: document.querySelector("#artifact-output"),
  error: document.querySelector("#error-output"),
  conversationTimeline: document.querySelector("#conversation-timeline"),
  conversationExportMarkdown: document.querySelector("#conversation-export-markdown"),
  conversationExportJson: document.querySelector("#conversation-export-json"),
  conversationExportZip: document.querySelector("#conversation-export-zip"),
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
  settingsSubnavigation: document.querySelector("#settings-subnavigation"),
  settingsSectionButtons: [...document.querySelectorAll("[data-settings-section]")],
  settingsSectionViews: [...document.querySelectorAll("[data-settings-view]")],
  contextPanel: document.querySelector("#context-panel"),
  skillsPanel: document.querySelector("#skills-panel"),
  settingsPanel: document.querySelector("#settings-panel"),
  identityLoginForm: document.querySelector("#identity-login-form"),
  identityUsername: document.querySelector("#identity-username"),
  identityPassword: document.querySelector("#identity-password"),
  identityAccountPanel: document.querySelector("#identity-account-panel"),
  identityAccountName: document.querySelector("#identity-account-name"),
  identityAccountRoles: document.querySelector("#identity-account-roles"),
  identitySessionStatus: document.querySelector("#identity-session-status"),
  identityDevelopmentWarning: document.querySelector("#identity-development-warning"),
  identityUsers: document.querySelector("#identity-users"),
  identityLogout: document.querySelector("#identity-logout"),
  identityStatus: document.querySelector("#identity-status"),
  runtimeDiagnostics: document.querySelector("#runtime-diagnostics"),
  contextCount: document.querySelector("#context-count"),
  attachmentInput: document.querySelector("#attachment-input"),
  attachmentFolderInput: document.querySelector("#attachment-folder-input"),
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
  skillFolderInput: document.querySelector("#skill-folder-input"),
  skillScanResults: document.querySelector("#skill-scan-results"),
  skillGithubUrl: document.querySelector("#skill-github-url"),
  skillGithubPreview: document.querySelector("#skill-github-preview"),
  skillGithubInstall: document.querySelector("#skill-github-install"),
  skillGithubStatus: document.querySelector("#skill-github-status"),
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
  uiPreset: document.querySelector("#ui-preset"),
  uiPresetDetails: document.querySelector("#ui-preset-details"),
  uiMode: document.querySelector("#ui-mode"),
  uiModeHelp: document.querySelector("#ui-mode-help"),
  uiDensity: document.querySelector("#ui-density"),
  uiTypography: document.querySelector("#ui-typography"),
  uiComponentOverrides: document.querySelector("#ui-component-overrides"),
  uiOverrideSummary: document.querySelector("#ui-override-summary"),
  uiPreviewStatus: document.querySelector("#ui-preview-status"),
  uiSave: document.querySelector("#ui-save"),
  uiCancel: document.querySelector("#ui-cancel"),
  uiResetPreset: document.querySelector("#ui-reset-preset"),
  uiRestoreDefaults: document.querySelector("#ui-restore-defaults"),
  approvedSkillDirectories: document.querySelector("#approved-skill-directories"),
  memoryEnabled: document.querySelector("#memory-enabled"),
  memoryDetailedRetention: document.querySelector("#memory-detailed-retention"),
  memorySearchLimit: document.querySelector("#memory-search-limit"),
  memorySettingsSave: document.querySelector("#memory-settings-save"),
  memorySettingsStatus: document.querySelector("#memory-settings-status"),
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
  workspaceShell: document.querySelector(".workspace-shell"),
  workspaceAnnouncer: document.querySelector("#workspace-announcer"),
  workspaceLeftDock: document.querySelector("#workspace-left-dock"),
  workspaceRightDock: document.querySelector("#workspace-right-dock"),
  workspaceBottomDock: document.querySelector("#workspace-bottom-dock"),
  workspaceSeparators: [...document.querySelectorAll(".workspace-separator")],
  workspaceLayoutMenu: document.querySelector("#workspace-layout-menu"),
  workspaceLayoutPopover: document.querySelector("#workspace-layout-popover"),
  workspaceFilesPanel: document.querySelector("#workspace-files-panel"),
  workspaceFilesList: document.querySelector("#workspace-files-list"),
  workspaceFilesAttach: document.querySelector("#workspace-files-attach"),
  workspaceSkillsPanel: document.querySelector("#workspace-skills-panel"),
  workspaceSkillsList: document.querySelector("#workspace-skills-list"),
  workspaceActivityPanel: document.querySelector("#workspace-activity-panel"),
  workspaceActivityNotice: document.querySelector("#workspace-activity-notice"),
  workspacePersistentNotice: document.querySelector("#workspace-persistent-notice"),
  workspaceActivityStop: document.querySelector("#workspace-activity-stop"),
  disabledComponents: document.querySelector("#disabled-components"),
  workspaceTabs: [...document.querySelectorAll("[data-workspace-mode]")],
  workspaceViews: [...document.querySelectorAll("[data-workspace-view]")],
  workspaceAgentForm: document.querySelector("#workspace-agent-form"),
  workspaceProjectRoot: document.querySelector("#workspace-project-root"),
  workspaceModel: document.querySelector("#workspace-model"),
  workspaceOutcome: document.querySelector("#workspace-outcome"),
  workspaceAgentRun: document.querySelector("#workspace-agent-run"),
  workspaceAgentApprove: document.querySelector("#workspace-agent-approve"),
  workspaceAgentStatus: document.querySelector("#workspace-agent-status"),
  workspaceAgentResult: document.querySelector("#workspace-agent-result"),
  terminalXterm: document.querySelector("#terminal-xterm"),
  terminalOutput: document.querySelector("#terminal-output"),
  terminalInput: document.querySelector("#terminal-input"),
  terminalRun: document.querySelector("#terminal-run"),
  terminalStop: document.querySelector("#terminal-stop"),
  terminalStatus: document.querySelector("#terminal-status"),
  taskActivity: document.querySelector("#task-activity"),
  taskSteer: document.querySelector("#task-steer"),
  taskStop: document.querySelector("#task-stop"),
  taskRetry: document.querySelector("#task-retry"),
  taskUndo: document.querySelector("#task-undo"),
  taskExecutionDetails: document.querySelector("#task-execution-details"),
  taskRequestedModel: document.querySelector("#task-requested-model"),
  taskEffectiveModel: document.querySelector("#task-effective-model"),
  taskPlanReviewOpen: document.querySelector("#task-plan-review-open"),
  taskPlanReview: document.querySelector("#task-plan-review"),
  taskPlanCanonical: document.querySelector("#task-plan-canonical"),
  taskPlanProse: document.querySelector("#task-plan-prose"),
  taskPlanStale: document.querySelector("#task-plan-stale"),
  taskPlanApprove: document.querySelector("#task-plan-approve"),
  taskPlanEdit: document.querySelector("#task-plan-edit"),
  taskPlanRequestChanges: document.querySelector("#task-plan-request-changes"),
  taskPlanReject: document.querySelector("#task-plan-reject"),
  taskStepSelect: document.querySelector("#task-step-select"),
  taskStepEdit: document.querySelector("#task-step-edit"),
  taskStepRequestChanges: document.querySelector("#task-step-request-changes"),
  taskStepReject: document.querySelector("#task-step-reject"),
};

const VALID_THEME_MODES = new Set(["light", "dark", "system"]);
const TERMINAL_SESSIONS_KEY = "json_codr_terminal_sessions";
const TERMINAL_COMMAND_HISTORY_KEY = "json_codr_terminal_command_history";
const NAVIGATION_DESTINATIONS = new Set(["workspace", "context", "skills", "hardware", "settings"]);
const HARDWARE_SECTIONS = new Set(["overview", "profiles", "runtimes", "compatibility", "model-search", "benchmarks", "leaderboard", "history", "localperf"]);
const SETTINGS_SECTIONS = new Set(["interface", "memory", "skills", "components", "disabled", "diagnostics"]);
const requestedNavigationDestination = window.JSONCodrNavigationRoutes?.destinationFromSearch(
  window.location.search,
  NAVIGATION_DESTINATIONS,
);
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
let xterm = null;
let terminalFitAddon = null;
let terminalKeyboardController = null;
let lastTerminalSequence = 0;
let activeTerminalProfile = "powershell";
let activeWorkspaceMode = "shell";
const terminalSessions = new Map();
let terminalPersistenceTimer = null;
let skillAttachmentId = null;
let editingSkill = null;
let skillLoadGeneration = 0;
let settingsState = null;
let skillFallbackToken = null;
let githubSkillPreviewId = null;
let settingsSaveQueue = Promise.resolve();
let themeSaveRevision = 0;
let skillsChangeRevision = 0;
let navigationChangeRevision = 0;
let activeDestination = "workspace";
let activeHardwareSection = "overview";
let activeSettingsSection = "interface";
let sidebarWidth = 260;
let persistedThemeMode = null;
let excludedSkillIds = [];
let pendingDestructiveAction = null;
let pendingActionProposalId = null;
let hardwareDetectionPromise = null;
let leaderboardHistoryCache = [];
let integrityHistoryCache = [];
let leaderboardCandidateCache = [];
const coreClient = new window.JSONCodrCoreClient();
const taskView = window.JSONCodrTaskView({
  activity: elements.taskActivity,
  steer: elements.taskSteer,
  stop: elements.taskStop,
  retry: elements.taskRetry,
  undo: elements.taskUndo,
  details: elements.taskExecutionDetails,
  requested: elements.taskRequestedModel,
  effective: elements.taskEffectiveModel,
});
let activeCoreTaskId = null;
let activeWorkspaceRoute = null;
let activePlanReview = null;
const conversationView = new window.JSONCodrConversationView({ timeline: elements.conversationTimeline });
let restoredConversationSessionId = null;
async function renderPlanReview(record) {
  const planEvent = [...(record.events || [])].reverse().find((event) => event.payload?.plan_id);
  if (!planEvent) return;
  const planId = planEvent.payload.plan_id;
  if (activePlanReview?.taskId === record.task_id && activePlanReview?.planId === planId && !activePlanReview.stale) return;
  const revisions = await coreClient.getPlanRevisions(record.task_id, planId);
  const plan = revisions.at(-1);
  if (!plan) return;
  activePlanReview = { taskId: record.task_id, planId, revision: plan.revision, plan, stale: false };
  elements.taskPlanCanonical.value = JSON.stringify(plan, null, 2);
  elements.taskPlanProse.value = "";
  elements.taskPlanStale.hidden = true;
  elements.taskStepSelect.replaceChildren(...plan.steps.map((step) => {
    const option = document.createElement("option"); option.value = step.step_id;
    option.textContent = `${step.step_id} · ${step.capability_id}.${step.operation}`; return option;
  }));
  elements.taskPlanReviewOpen.hidden = false;
}

async function submitPlanReview(action) {
  if (!activePlanReview) return;
  let plan = null;
  if (["approve", "edit", "revise"].includes(action)) plan = JSON.parse(elements.taskPlanCanonical.value);
  try {
    const result = await coreClient.revisePlan(activePlanReview.taskId, activePlanReview.planId, {
      expectedRevision: activePlanReview.revision, action, plan, reason: elements.taskPlanProse.value.trim() || null,
    });
    if (result?.revision) {
      activePlanReview = { ...activePlanReview, revision: result.revision, plan: result, stale: false };
      elements.taskPlanCanonical.value = JSON.stringify(result, null, 2);
    }
  } catch (error) {
    if (/stale|revision|conflict/i.test(error.message)) {
      activePlanReview.stale = true; elements.taskPlanStale.hidden = false;
    }
    throw error;
  }
}

async function submitStepReview(action) {
  if (!activePlanReview || !elements.taskStepSelect.value) return;
  const parsed = JSON.parse(elements.taskPlanCanonical.value);
  const step = parsed.steps.find((item) => item.step_id === elements.taskStepSelect.value) || null;
  try {
    const result = await coreClient.reviseStep(activePlanReview.taskId, activePlanReview.planId, elements.taskStepSelect.value, {
      expectedRevision: activePlanReview.revision, action,
      step: ["approve", "edit", "revise"].includes(action) ? step : null,
      reason: elements.taskPlanProse.value.trim() || null,
    });
    if (result?.revision) {
      activePlanReview = { ...activePlanReview, revision: result.revision, plan: result, stale: false };
      elements.taskPlanCanonical.value = JSON.stringify(result, null, 2);
    }
  } catch (error) {
    if (/stale|revision|conflict/i.test(error.message)) {
      activePlanReview.stale = true; elements.taskPlanStale.hidden = false;
    }
    throw error;
  }
}

function handleCoreRecord(record) {
  if (record.task_id !== activeCoreTaskId) return;
  taskView.render(record);
  renderPlanReview(record).catch((error) => showError(error.message));
  const latestEvent = (record.events || []).at(-1);
  renderWorkspaceActivityNotice(latestEvent?.event_type || record.status, record.status);
  const message = conversationView.apply(record);
  const completion = [...(record.events || [])].reverse().find((item) => item.event_type === "inference.completed");
  if (completion) {
    const payload = completion.payload.result;
    markOllamaReady();
    elements.responseModel.textContent = completion.payload.effective_model_id || payload.model;
    renderAttachedSkills(payload.attached_skills || []);
    renderRecommendations(payload.skill_recommendations || []);
    renderActions(payload.action_proposals || []);
    elements.artifactOutput.hidden = !payload.artifact;
    if (payload.artifact) {
      elements.artifactOutput.href = payload.artifact.url;
      elements.artifactOutput.textContent = `Download ${payload.artifact.filename}`;
    }
  }
  if (["completed", "failed", "cancelled", "interrupted"].includes(record.status)) {
    conversationView.persistCompleted(record.task_id).catch((error) => showError(error.message));
    setPending(false);
    if (!completion && message?.error) elements.requestStatus.textContent = message.error;
  }
}
coreClient.subscribe(handleCoreRecord);
let selectedLeaderboardSessionId = null;
let selectedLeaderboardRowId = null;
let leaderboardSort = { key: "rank", direction: "asc" };
const actionButtons = new Map();
const workspacePanels = new Map();
const workspaceHosts = {
  left: elements.workspaceLeftDock,
  right: elements.workspaceRightDock,
  bottom: elements.workspaceBottomDock,
};
const workspaceLayout = window.createWorkspaceLayoutController({
  availablePanels: ["skills", "activity", "terminal"],
  panelPlacements: {
    skills: ["left", "right", "bottom"],
    activity: ["right", "left", "bottom"],
    terminal: ["bottom", "left", "right"],
  },
});

function registerWorkspacePanel({ id, element, allowedPlacements, managementDestination = null, onShown = null }) {
  if (!id || !element || workspacePanels.has(id)) return false;
  workspacePanels.set(id, { id, element, allowedPlacements, managementDestination, onShown });
  return true;
}

function getActiveWorkspacePanels(components) {
  const disabled = new Set(
    components.filter((component) => component.available === false).map((component) => component.workspacePanel).filter(Boolean),
  );
  return ["files", "skills", "activity", "terminal"].filter((panelId) => !disabled.has(panelId));
}

function renderDisabledComponents(components) {
  if (!elements.disabledComponents) return;
  const disabled = components.filter((component) => component.available === false);
  elements.disabledComponents.replaceChildren();
  if (!disabled.length) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No disabled components.";
    elements.disabledComponents.append(empty); return;
  }
  for (const component of disabled) {
    const unavailableReason = component.reason || "Required runtime or installation was not verified.";
    const statusSource = component.statusSource || "component registry";
    const row = document.createElement("article"); row.className = "dependency-item";
    const title = document.createElement("strong"); title.textContent = component.name || component.component_id;
    const detail = document.createElement("p"); detail.className = "meta";
    detail.textContent = `${unavailableReason} · Status source: ${statusSource}`;
    const enable = document.createElement("button"); enable.type = "button"; enable.className = "secondary";
    enable.textContent = "Enable or configure";
    enable.addEventListener("click", () => selectDestination(component.destination || "settings"));
    row.append(title, detail, enable); elements.disabledComponents.append(row);
  }
}

function renderWorkspaceFiles(attachments) {
  for (const list of [elements.workspaceFilesList, elements.workspaceFilesPopoverList]) {
    if (!list) continue;
    list.replaceChildren();
    if (!attachments.length) {
      const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No files attached.";
      list.append(empty); continue;
    }
    for (const attachment of attachments) {
      const row = document.createElement("div"); row.className = "workspace-quick-row";
      const name = document.createElement("span"); name.textContent = attachment.display_name;
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Remove";
      remove.addEventListener("click", async () => {
        await fetch(`/api/sessions/${sessionId}/attachments/${attachment.id}`, { method: "DELETE" });
        await loadAttachments();
      });
      row.append(name, remove); list.append(row);
    }
  }
}

function closeWorkspaceFilesPopover({ restoreFocus = false } = {}) {
  if (!elements.workspaceFilesPopover?.matches(":popover-open")) return;
  elements.workspaceFilesPopover.hidePopover();
  if (restoreFocus) elements.workspaceAttach.focus();
}

function positionWorkspaceFilesPopover() {
  if (!elements.workspaceFilesPopover.matches(":popover-open")) return;
  const anchor = elements.workspaceAttach.getBoundingClientRect();
  const margin = 12;
  const width = Math.min(280, Math.max(0, window.innerWidth - margin * 2));
  const left = Math.max(margin, Math.min(anchor.left, window.innerWidth - width - margin));
  elements.workspaceFilesPopover.style.width = `${width}px`;
  elements.workspaceFilesPopover.style.left = `${left}px`;
  elements.workspaceFilesPopover.style.top = `${anchor.bottom + 8}px`;
  const popup = elements.workspaceFilesPopover.getBoundingClientRect();
  const top = Math.min(anchor.bottom + 8, window.innerHeight - popup.height - margin);
  elements.workspaceFilesPopover.style.top = `${Math.max(margin, top)}px`;
}

function renderWorkspaceSkills(packs, selected) {
  if (!elements.workspaceSkillsList) return;
  elements.workspaceSkillsList.replaceChildren();
  const skills = packs.flatMap((pack) => pack.skills.map((skill) => ({ pack, skill })));
  if (!skills.length) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No skills installed.";
    elements.workspaceSkillsList.append(empty); return;
  }
  for (const { pack, skill } of skills) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input"); checkbox.type = "checkbox";
    checkbox.value = `${pack.id}:${skill.id}`; checkbox.checked = selected.has(checkbox.value); checkbox.disabled = !skill.enabled;
    checkbox.addEventListener("change", async () => {
      const selected = [...elements.workspaceSkillsList.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
      await saveSkillSelection(selected); await loadSkills();
    });
    label.append(checkbox, document.createTextNode(` ${skill.name}`)); elements.workspaceSkillsList.append(label);
  }
}

function renderWorkspaceActivityNotice(message = "Ready", status = "idle") {
  const text = status === "running" ? `${message} · Stop is available in Activity` : message;
  if (elements.workspaceActivityNotice) elements.workspaceActivityNotice.textContent = text;
  if (elements.workspacePersistentNotice) elements.workspacePersistentNotice.textContent = text;
  if (elements.workspaceActivityStop) elements.workspaceActivityStop.hidden = status !== "running";
  if (["completed", "failed", "approval_required"].includes(status) && elements.workspaceAnnouncer) {
    elements.workspaceAnnouncer.textContent = `${status.replace("_", " ")}: ${message}`;
  }
}

async function loadRuntimeDiagnostics() {
  if (!elements.runtimeDiagnostics) return;
  elements.runtimeDiagnostics.innerHTML = '<p class="meta">Reading local runtime evidence…</p>';
  try {
    const response = await fetch("/api/runtime/status");
    if (!response.ok) throw new Error(await responseErrorMessage(response, "Runtime diagnostics failed"));
    const status = await response.json();
    elements.runtimeDiagnostics.replaceChildren();
    const locality = document.createElement("p"); locality.className = "meta";
    locality.textContent = `${status.local_only ? "Local only" : "External routes enabled"} · ${status.health}`;
    elements.runtimeDiagnostics.append(locality);
    for (const heartbeat of status.heartbeats || []) {
      const row = document.createElement("article"); row.className = "dependency-item";
      const title = document.createElement("strong"); title.textContent = heartbeat.runtime_id;
      const detail = document.createElement("p"); detail.className = "meta";
      detail.textContent = heartbeat.stale ? "Heartbeat stale · restart or inspect the supervisor" : `${heartbeat.status} · PID ${heartbeat.pid}`;
      row.append(title, detail); elements.runtimeDiagnostics.append(row);
    }
    for (const item of (status.telemetry || []).slice(-20).reverse()) {
      const row = document.createElement("article"); row.className = "dependency-item";
      const title = document.createElement("strong"); title.textContent = item.kind;
      const detail = document.createElement("p"); detail.className = "meta";
      detail.textContent = JSON.stringify(item.payload);
      row.append(title, detail); elements.runtimeDiagnostics.append(row);
    }
  } catch (error) {
    elements.runtimeDiagnostics.innerHTML = `<p class="error">${error.message}</p>`;
  }
}

function workspaceRegionForPanel(state, panelId) {
  return ["left", "right", "bottom"].find((region) => state.regions[region].includes(panelId)) || null;
}

function renderWorkspaceLayout(state = workspaceLayout.getState()) {
  elements.workspaceShell.setAttribute("data-workspace-mode", state.mode || "wide");
  for (const [region, host] of Object.entries(workspaceHosts)) {
    const panelIds = state.regions[region].filter((id) => workspacePanels.has(id));
    for (const panelId of panelIds) {
      const panel = workspacePanels.get(panelId);
      if (panel.element.parentElement !== host) host.append(panel.element);
      panel.element.hidden = state.collapsed[region];
      panel.element.dataset.workspacePanel = panelId;
      if (!state.collapsed[region]) panel.onShown?.();
    }
    host.hidden = panelIds.length === 0 || state.collapsed[region];
    elements.workspaceShell.style.setProperty(`--workspace-${region}-size`, `${state.sizes[region]}px`);
    const separator = elements.workspaceSeparators.find((item) => item.classList.contains(`workspace-separator-${region}`));
    if (separator) {
      separator.hidden = host.hidden;
      separator.setAttribute("aria-valuenow", String(state.sizes[region]));
      separator.setAttribute("aria-valuetext", `${state.sizes[region]} pixels`);
    }
  }
}

function openWorkspacePanel(id, placement = null) {
  const panel = workspacePanels.get(id);
  if (!panel) return false;
  const current = workspaceRegionForPanel(workspaceLayout.getState(), id);
  const target = panel.allowedPlacements.includes(placement) ? placement : current || panel.allowedPlacements[0];
  renderWorkspaceLayout(workspaceLayout.open(id, target));
  panel.element.focus?.({ preventScroll: true });
  return true;
}

function focusWorkspaceRegion(region) {
  const state = workspaceLayout.getState();
  const id = state.regions[region]?.at(-1);
  if (!id) return false;
  renderWorkspaceLayout(workspaceLayout.focus(id));
  workspacePanels.get(id)?.element.focus?.({ preventScroll: true });
  return true;
}

function bindWorkspaceSeparator(separator) {
  const region = ["left", "right", "bottom"].find((name) => separator.classList.contains(`workspace-separator-${name}`));
  if (!region) return;
  const commitSize = (value) => renderWorkspaceLayout(workspaceLayout.resize(region, value));
  separator.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    separator.setPointerCapture(event.pointerId);
    const start = region === "bottom" ? event.clientY : event.clientX;
    const initial = workspaceLayout.getState().sizes[region];
    let pending = initial;
    let frame = null;
    const onMove = (moveEvent) => {
      const current = region === "bottom" ? moveEvent.clientY : moveEvent.clientX;
      const direction = region === "right" || region === "bottom" ? -1 : 1;
      pending = initial + ((current - start) * direction);
      if (frame === null) frame = requestAnimationFrame(() => { frame = null; commitSize(pending); });
    };
    const onUp = () => {
      separator.removeEventListener("pointermove", onMove);
      if (frame !== null) cancelAnimationFrame(frame);
      commitSize(pending);
    };
    separator.addEventListener("pointermove", onMove);
    separator.addEventListener("pointerup", onUp, { once: true });
  });
  separator.addEventListener("keydown", (event) => {
    const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -10
      : event.key === "ArrowRight" || event.key === "ArrowDown" ? 10 : 0;
    if (!delta) return;
    event.preventDefault();
    commitSize(workspaceLayout.getState().sizes[region] + delta);
  });
  separator.addEventListener("dblclick", () => commitSize(region === "left" ? 260 : region === "right" ? 300 : 260));
}

const dependencyInstallQueue = createDependencyInstallQueue(async (command) => {
  openWorkspacePanel("terminal", "bottom");
  selectDestination("workspace");
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

function applyAppearanceState(effective) {
  document.documentElement.dataset.theme = effective.effectiveMode;
  document.documentElement.style.colorScheme = effective.effectiveMode;
  document.documentElement.dataset.uiPreset = effective.preset;
  document.documentElement.dataset.uiDensity = effective.density;
  document.documentElement.dataset.uiTypography = effective.typography;
  for (const [family, variant] of Object.entries(effective.components)) {
    document.documentElement.dataset[`ui${family[0].toUpperCase()}${family.slice(1)}`] = variant;
  }
}

const uiCustomizationController = window.createUICustomizationController({
  catalog: window.JSONCodrUICatalog,
  apply: applyAppearanceState,
  announce: (message) => { if (elements.uiPreviewStatus) elements.uiPreviewStatus.textContent = message; },
});
const uiCustomizationEditor = window.bindUICustomizationEditor({
  controller: uiCustomizationController,
  catalog: window.JSONCodrUICatalog,
  elements: {
    preset: elements.uiPreset, presetDetails: elements.uiPresetDetails, mode: elements.uiMode, modeHelp: elements.uiModeHelp,
    density: elements.uiDensity, typography: elements.uiTypography,
    components: elements.uiComponentOverrides, summary: elements.uiOverrideSummary,
    status: elements.uiPreviewStatus, save: elements.uiSave, cancel: elements.uiCancel,
    resetPreset: elements.uiResetPreset, restoreDefaults: elements.uiRestoreDefaults,
  },
});

systemThemeQuery.addEventListener("change", () => {
  if (uiCustomizationController.getDraft().mode === "system") {
    applyAppearanceState(uiCustomizationController.getEffectiveState());
  }
});

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

function selectSettingsSection(section, { focus = false } = {}) {
  if (!SETTINGS_SECTIONS.has(section)) section = "interface";
  activeSettingsSection = section;
  for (const button of elements.settingsSectionButtons) {
    if (button.dataset.settingsSection === section) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const view of elements.settingsSectionViews) view.hidden = view.dataset.settingsView !== section;
  if (focus) {
    elements.settingsSectionViews
      .find((view) => view.dataset.settingsView === section)
      ?.querySelector("h3, strong, summary")
      ?.focus({ preventScroll: true });
  }
  if (section === "diagnostics") loadRuntimeDiagnostics();
}

function selectDestination(destination, { persist = true, focus = false } = {}) {
  if (destination === "terminal") {
    openWorkspacePanel("terminal", "bottom");
    destination = "workspace";
  }
  if (!NAVIGATION_DESTINATIONS.has(destination)) destination = "workspace";
  activeDestination = destination;
  for (const button of elements.navigationButtons) {
    const selected = button.dataset.destination === destination;
    button.classList.toggle("is-active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const view of elements.destinationViews) view.hidden = view.dataset.view !== destination;
  elements.hardwareSubnavigation.hidden = destination !== "hardware";
  elements.settingsSubnavigation.hidden = destination !== "settings";
  if (destination === "hardware") selectHardwareSection(activeHardwareSection, { persist: false });
  if (destination === "settings") selectSettingsSection(activeSettingsSection);
  if (destination === "terminal") {
    initializeXterm();
    if (!terminalId) elements.terminalStatus.textContent = "PowerShell is ready to start";
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

function normalizeTerminalOutput(text) {
  if (String(text).toLowerCase().includes("does not support tools")) {
    return "This model uses the JSON_CODR broker adapter for project tools. Select Git broker and launch the delegated task.\n";
  }
  return text;
}

function appendTerminalOutput(text) {
  text = normalizeTerminalOutput(text);
  if (xterm) xterm.write(text);
  elements.terminalOutput.textContent += text;
  elements.terminalOutput.scrollTop = elements.terminalOutput.scrollHeight;
}

async function ensureTerminal() {
  const activeSession = terminalSessions.get(activeTerminalProfile);
  if (terminalSocket?.readyState === WebSocket.OPEN && terminalId === activeSession?.terminal?.id) return;
  if (terminalConnectionPromise) return terminalConnectionPromise;
  terminalConnectionPromise = createTerminalConnection();
  try {
    await terminalConnectionPromise;
  } finally {
    terminalConnectionPromise = null;
  }
}

function persistTerminalSessions() {
  const sessions = {};
  for (const [profile, session] of terminalSessions) {
    if (session.terminal?.id) {
      sessions[profile] = { id: session.terminal.id, lastSequence: session.lastSequence || 0 };
    }
  }
  localStorage.setItem(TERMINAL_SESSIONS_KEY, JSON.stringify(sessions));
}

function scheduleTerminalSessionPersistence() {
  if (terminalPersistenceTimer) return;
  terminalPersistenceTimer = window.setTimeout(() => {
    terminalPersistenceTimer = null;
    persistTerminalSessions();
  }, 200);
}

async function restoreTerminalSessions() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(TERMINAL_SESSIONS_KEY) || "{}");
  } catch (_error) {
    localStorage.removeItem(TERMINAL_SESSIONS_KEY);
  }
  const response = await fetch("/api/terminals");
  if (!response.ok) return;
  const available = new Map(
    (await response.json())
      .filter((terminal) => !terminal.external)
      .map((terminal) => [terminal.id, terminal]),
  );
  for (const [profile, session] of Object.entries(saved)) {
    const terminal = available.get(session.id);
    if (terminal) terminalSessions.set(profile, { terminal, lastSequence: session.lastSequence || 0 });
  }
  persistTerminalSessions();
}

function initializeXterm() {
  if (xterm || !window.Terminal || !elements.terminalXterm) return;
  xterm = new window.Terminal({
    convertEol: true,
    cursorBlink: true,
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
    fontSize: 13,
    scrollback: 5000,
    theme: { background: "#090d12", foreground: "#e8edf4", cursor: "#b7ff32" },
  });
  terminalFitAddon = new window.FitAddon.FitAddon();
  xterm.loadAddon(terminalFitAddon);
  xterm.open(elements.terminalXterm);
  terminalFitAddon.fit();
  elements.terminalOutput.hidden = true;
  terminalKeyboardController = window.createTerminalKeyboardController({
    copyText: async (text) => {
      try {
        await navigator.clipboard.writeText(text);
      } catch (error) {
        appendTerminalOutput(`Clipboard copy failed: ${error.message}\n`);
      }
    },
    interrupt: () => {
      if (terminalSocket?.readyState === WebSocket.OPEN) {
        terminalSocket.send(JSON.stringify({ type: "interrupt" }));
      }
    },
    loadHistory: () => JSON.parse(localStorage.getItem(TERMINAL_COMMAND_HISTORY_KEY) || "[]"),
    saveHistory: (history) => localStorage.setItem(TERMINAL_COMMAND_HISTORY_KEY, JSON.stringify(history)),
  });
  xterm.attachCustomKeyEventHandler((event) => terminalKeyboardController.handleKeyEvent(
    event,
    xterm.hasSelection() ? xterm.getSelection() : "",
  ));
  xterm.onData((data) => {
    // ConPTY queries terminal capabilities while PowerShell starts. xterm answers
    // those queries through onData, but PowerShell treats the answers as typed
    // input and leaves them in its command buffer.
    if (/^\x1b\[(?:\?|>)[0-9;]*c$/.test(data)) return;
    if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(JSON.stringify({ type: "input", data }));
  });
  xterm.onResize(({ cols, rows }) => {
    if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(JSON.stringify({ type: "resize", cols, rows }));
  });
  new ResizeObserver(() => {
    terminalFitAddon.fit();
  }).observe(elements.terminalXterm);
}

async function createTerminalConnection(profile = "powershell") {
  initializeXterm();
  elements.terminalStatus.textContent = "Starting...";
  const response = await fetch("/api/terminals", {
    method: "POST",
    headers: window.JSONCodrHttpIdentity.mutationHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ shell: "powershell" }),
  });
  if (!response.ok) throw new Error((await response.json()).detail || "Unable to start terminal");
  const terminal = await response.json();
  await connectTerminalRecord(terminal, profile);
}

async function closeActiveTerminal() {
  const previousId = terminalId;
  const previousSocket = terminalSocket;
  terminalId = null;
  terminalSocket = null;
  if (previousSocket) previousSocket.close();
  if (!previousId) return;
  const response = await fetch(`/api/terminals/${previousId}`, {
    method: "DELETE",
    headers: window.JSONCodrHttpIdentity.mutationHeaders(),
  });
  if (!response.ok && response.status !== 404) {
    throw new Error((await response.json()).detail || "Unable to close the previous terminal");
  }
  for (const [profile, session] of terminalSessions) {
    if (session.terminal?.id === previousId) terminalSessions.delete(profile);
  }
  persistTerminalSessions();
}

async function connectTerminalRecord(terminal, profile = activeTerminalProfile) {
  initializeXterm();
  const storedSession = terminalSessions.get(profile) || { lastSequence: 0 };
  if (storedSession.terminal?.id !== terminal.id) storedSession.lastSequence = 0;
  storedSession.terminal = terminal;
  terminalSessions.set(profile, storedSession);
  persistTerminalSessions();
  if (profile !== activeTerminalProfile) return;
  if (terminalSocket) terminalSocket.close();
  terminalId = terminal.id;
  const session = storedSession;
  // The shared xterm surface is cleared when profiles change, so replay this
  // profile's bounded server history instead of resuming into a blank screen.
  lastTerminalSequence = 0;
  if (xterm) xterm.clear();
  elements.terminalOutput.textContent = "";
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const csrfProtocol = window.JSONCodrHttpIdentity.websocketCsrfProtocol();
  const socket = new WebSocket(`${protocol}//${location.host}/ws/terminals/${terminalId}?after_seq=${lastTerminalSequence}`, csrfProtocol || undefined);
  terminalSocket = socket;
  terminalSocket.addEventListener("open", () => {
    elements.terminalStatus.textContent = `${terminal.shell} · PID ${terminal.pid}`;
    terminalSocket.send(JSON.stringify({ type: "attach", after_seq: lastTerminalSequence }));
    if (terminal.backend === "conpty" && terminalFitAddon) terminalFitAddon.fit();
  });
  terminalSocket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "output") {
      appendTerminalOutput(message.data);
      if (Number.isInteger(message.seq)) {
        lastTerminalSequence = message.seq;
        session.lastSequence = message.seq;
        scheduleTerminalSessionPersistence();
      }
    }
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
    if (terminalSocket !== socket) return;
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
    headers: window.JSONCodrHttpIdentity.mutationHeaders({ "Content-Type": "application/json" }),
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
  command = command.trim();
  if (!command) return;
  if (command === "clr --history") {
    if (xterm) xterm.clear();
    elements.terminalOutput.textContent = "";
    if (fromInput) elements.terminalInput.value = "";
    return;
  }
  if (command === "clr --command") {
    terminalKeyboardController?.clearCommandHistory();
    if (fromInput) elements.terminalInput.value = "";
    return;
  }
  if (fromInput) terminalKeyboardController?.recordCommand(command);
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
  if (!sessionId || !(await fetch(`/api/sessions/${sessionId}`)).ok) {
    const session = await fetch("/api/sessions", { method: "POST" }).then((response) => response.json());
    sessionId = session.id;
    localStorage.setItem("json_codr_session", sessionId);
  }
  if (restoredConversationSessionId !== sessionId) {
    await conversationView.restore(sessionId);
    restoredConversationSessionId = sessionId;
    elements.empty.hidden = conversationView.messages.length > 0;
  }
  const base = `/api/sessions/${encodeURIComponent(sessionId)}/conversation/export`;
  elements.conversationExportMarkdown.href = `${base}?format=markdown`;
  elements.conversationExportJson.href = `${base}?format=json`;
  elements.conversationExportZip.href = `${base}?format=zip&include_binaries=true`;
  return sessionId;
}

function selectWorkspaceMode(mode) {
  activeWorkspaceMode = mode === "agent" ? "agent" : "shell";
  for (const tab of elements.workspaceTabs) {
    tab.setAttribute("aria-selected", String(tab.dataset.workspaceMode === activeWorkspaceMode));
  }
  for (const view of elements.workspaceViews) view.hidden = view.dataset.workspaceView !== activeWorkspaceMode;
  if (activeWorkspaceMode === "shell") {
    initializeXterm();
    terminalFitAddon?.fit();
  }
}

async function runWorkspaceAgent() {
  const projectRoot = elements.workspaceProjectRoot.value.trim();
  const model = elements.workspaceModel.value;
  const outcome = elements.workspaceOutcome.value.trim();
  if (!projectRoot || !model || !outcome) return;
  elements.workspaceAgentRun.disabled = true;
  elements.workspaceAgentApprove.hidden = true;
  elements.workspaceAgentStatus.textContent = "BORG is inspecting the project and executing the verified action plan…";
  elements.workspaceAgentResult.textContent = "Task running…";
  localStorage.setItem("json_codr_workspace_project_root", projectRoot);
  try {
    await ensureSession();
    const response = await fetch("/api/workspace/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_root: projectRoot, session_id: sessionId, engine_id: "borg",
        model_selection: model, prompt: outcome,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Project task failed");
    elements.workspaceAgentStatus.textContent = `${payload.route} · requested ${payload.requested_model} · effective ${payload.effective_model || "all installed models"}`;
    elements.workspaceAgentResult.textContent = JSON.stringify(payload.result, null, 2);
    if (payload.status === "approval_required" && !showWorkspaceAgentApproval(payload.result?.task, payload.task_id)) {
      throw new Error("Agent approval is missing its proposal identity");
    }
  } catch (error) {
    elements.workspaceAgentStatus.textContent = "Agent task failed";
    elements.workspaceAgentResult.textContent = error.message;
  } finally {
    elements.workspaceAgentRun.disabled = false;
  }
}

function showWorkspaceAgentApproval(task, taskId) {
  if (["completed", "failed", "cancelled"].includes(task?.status)) return false;
  const completedSteps = new Set(
    (task?.events || [])
      .filter((event) => event.event_type === "agent.action_completed")
      .map((event) => event.payload?.step_id),
  );
  const approval = [...(task?.events || [])].reverse().find(
    (event) => event.event_type === "agent.approval_required"
      && !completedSteps.has(event.payload?.step_id),
  );
  if (!approval?.payload?.proposal_id) return false;
  elements.workspaceAgentApprove.dataset.taskId = taskId;
  elements.workspaceAgentApprove.dataset.proposalId = approval.payload.proposal_id;
  elements.workspaceAgentApprove.hidden = false;
  elements.workspaceAgentStatus.textContent = "Approval required · review and approve the proposed project action";
  return true;
}

async function approveWorkspaceAgentAction() {
  const taskId = elements.workspaceAgentApprove.dataset.taskId;
  const proposalId = elements.workspaceAgentApprove.dataset.proposalId;
  if (!taskId || !proposalId) return;
  elements.workspaceAgentApprove.disabled = true;
  elements.workspaceAgentStatus.textContent = "Executing the approved project action…";
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: "project", proposal_id: proposalId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Unable to approve the project action");
    elements.workspaceAgentResult.textContent = JSON.stringify(payload, null, 2);
    if (!showWorkspaceAgentApproval(payload, taskId)) {
      elements.workspaceAgentStatus.textContent = `Agent task ${payload.status}`;
      elements.workspaceAgentApprove.hidden = true;
    }
  } catch (error) {
    elements.workspaceAgentStatus.textContent = "Agent approval failed";
    elements.workspaceAgentResult.textContent = error.message;
  } finally {
    elements.workspaceAgentApprove.disabled = false;
  }
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
  if (themeRevisionAtStart === themeSaveRevision && !localStorage.getItem(window.JSONCodrUICatalog.STORAGE_KEY)) {
    uiCustomizationController.seedLegacyMode(persistedThemeMode);
    uiCustomizationEditor.render();
  }
  if (navigationRevisionAtStart === navigationChangeRevision) {
    applySidebarWidth(settingsState.ui.sidebar_width);
    setSidebarCollapsed(settingsState.ui.sidebar_collapsed, { persist: false });
    selectHardwareSection(settingsState.ui.hardware_section, { persist: false });
    selectDestination(requestedNavigationDestination || settingsState.ui.primary_destination, { persist: false });
  }
  if (skillsRevisionAtStart === skillsChangeRevision) {
    elements.settingSkillsOpen.checked = settingsState.ui.primary_destination === "skills";
  }
  elements.settingSkillsOpen.disabled = false;
  elements.memoryEnabled.checked = settingsState.memory.enabled;
  elements.memoryDetailedRetention.checked = settingsState.memory.detailed_retention_enabled;
  elements.memorySearchLimit.value = settingsState.memory.search_limit;
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
    const [response, catalogResponse, environmentResponse] = await Promise.all([
      fetch("/api/hardware/detect", { method: "POST" }),
      fetch("/api/inference/catalog"),
      fetch("/api/inference/environments"),
    ]);
    if (!response.ok) throw new Error(await responseErrorMessage(response, "Hardware detection failed"));
    const candidates = await response.json();
    leaderboardCandidateCache = candidates.map((candidate) => ({ ...candidate }));
    const optimizedCatalog = catalogResponse.ok ? await catalogResponse.json() : [];
    const providerEnvironments = environmentResponse.ok ? await environmentResponse.json() : [];
    const compatibility = candidates.map((candidate) => ({
      backend: candidate.id,
      backend_name: candidate.name,
      models: candidate.compatible_models || [],
    }));
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
        const agents = model.agent_compatibility;
        const routeState = agents?.native_tools_verified
          ? "native tool route verified"
          : agents?.tool_route === "delegated_verified"
            ? `delegated tool route verified via ${agents.effective_tool_model}`
            : "agent tools unavailable or unverified";
        const sessionState = agents?.continue_verified && agents?.aider_verified
          ? "Coding workflow verified"
          : agents?.tool_route_verified
            ? "Coding workflow not verified on this profile"
            : "Coding workflow unavailable";
        const agentState = `${routeState} · ${sessionState}`;
        line.textContent = `${model.model} · ${state} · ${agentState}${model.reason ? ` · ${model.reason}` : ""}`;
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
          const agents = model.agent_compatibility;
          const routeState = agents?.native_tools_verified
            ? "native tool route verified"
            : agents?.tool_route === "delegated_verified"
              ? `delegated tool route via ${agents.effective_tool_model}`
              : "agent tools unverified";
          const agentState = agents?.continue_verified && agents?.aider_verified
            ? `${routeState} · coding workflow verified`
            : `${routeState} · coding workflow not verified on this profile`;
          line.textContent = `${model.model} · ${state} · ${agentState}${model.reason ? ` · ${model.reason}` : ""}`;
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
  base_log_perplexity: ["Base log-perplexity", ""],
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
  if (metric === "holistic_capability" || metric === "integrity_overall" || metric === "combined_score" || metric === "base_log_perplexity") {
    const note = document.createElement("p"); note.className = "meta";
    note.textContent = metric === "base_log_perplexity"
      ? "Base log-perplexity uses the latest comparable v3 teacher-forced evaluation on the fixed JSON_CODR corpus; unsupported runtimes remain unranked."
      : "Quality ranks use the latest strict integrity evaluation. Review its per-scenario history in Performance benchmarks.";
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
  const languageMetric = document.createElement("p");
  languageMetric.textContent = row.log_perplexity_comparable
    ? `Base log-perplexity ${formatLeaderboardValue(row.base_log_perplexity, "", 4)} · ${row.log_perplexity_dataset} · lower is better`
    : `Base log-perplexity unavailable${row.log_perplexity_reason ? `: ${row.log_perplexity_reason}` : "."}`;
  elements.leaderboardDetails.append(languageMetric);
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
    elements.leaderboardTable.replaceChildren(); const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 12; cell.className = "meta"; cell.textContent = "No benchmark history. Run Performance benchmarks first."; row.append(cell); elements.leaderboardTable.append(row);
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
    const values = [row.rank || "—", `${row.model} · ${row.name}`, formatLeaderboardValue(row.performance_index, "", 0), formatLeaderboardValue(row.integrity_overall, "%", 1), formatLeaderboardValue(row.base_log_perplexity, "", 4), formatLeaderboardValue(row.combined_score, "", 1), formatLeaderboardValue(row.tokens_per_second), formatLeaderboardValue(row.ttft_ms, " ms", 0), formatLeaderboardValue(row.average_total_seconds, " s"), formatLeaderboardValue(row.peak_vram_mb, " MiB", 0), formatLeaderboardValue(row.speedup_vs_cpu, "×"), evidenceStatus];
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
  const languageMetric = benchmark.language_model_metrics;
  if (languageMetric) {
    const card = document.createElement("article");
    const caption = document.createElement("span"); caption.className = "meta"; caption.textContent = "Base log-perplexity";
    const score = document.createElement("strong");
    score.textContent = languageMetric.status === "measured" && languageMetric.comparable
      ? Number(languageMetric.base_log_perplexity).toFixed(4) : "Unavailable";
    const evidence = document.createElement("span"); evidence.className = "meta";
    evidence.textContent = languageMetric.status === "measured" && languageMetric.comparable
      ? `${languageMetric.dataset_id}@${languageMetric.dataset_version} · ${languageMetric.token_count} tokens · lower is better`
      : languageMetric.unavailable_reason || languageMetric.status;
    card.append(caption, score, evidence); elements.integrityBenchmarkScores.append(card);
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
    const logPerplexity = benchmark.language_model_metrics;
    const metricStatus = logPerplexity?.status === "measured" && logPerplexity?.comparable
      ? ` · ${Number(logPerplexity.base_log_perplexity).toFixed(4)} base log-perplexity`
      : " · base log-perplexity unavailable";
    elements.integrityBenchmarkStatus.textContent = `Evaluation complete · ${Number(benchmark.scores.overall).toFixed(1)}% overall${metricStatus}`;
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
      const install = document.createElement("button"); install.className = "secondary"; install.type = "button";
      install.textContent = model.source === "pinned" ? "Download and install" : "Not approved for install";
      install.disabled = model.source !== "pinned";
      install.addEventListener("click", async () => {
        if (!window.confirm(`Download ${model.repository} from its pinned Hugging Face revision, install its local runtime, and register it for JSON_CODR?`)) return;
        install.disabled = true; install.textContent = "Downloading and installing…";
        try {
          const response = await fetch("/api/inference/models/install", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({model_id: model.id, confirmed: true}),
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || "Model installation failed");
          install.textContent = result.verified ? "Installed and verified" : "Installed · probe required";
          detail.textContent = `${model.provider} · installed locally · ${result.verified ? "available" : result.probe_error || "restart optimized routing to probe"}`;
          await Promise.all([loadModels(), detectHardware()]);
        } catch (error) {
          install.disabled = false; install.textContent = "Retry download and install";
          detail.textContent = `${model.provider} · installation failed · ${error.message}`;
        }
      });
      label.append(name, detail); row.append(label, install); elements.optimizedModelSearchResults.append(row);
    }
  } finally { elements.optimizedModelSearchRun.disabled = false; }
}

async function loadAttachments() {
  await ensureSession();
  elements.exportArchive.href = `/api/sessions/${sessionId}/archive.zip`;
  const attachments = await fetch(`/api/sessions/${sessionId}/attachments`).then((response) => response.json());
  renderWorkspaceFiles(attachments);
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

async function saveSkillSelection(selected = null) {
  selected = selected || [...elements.skillList.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
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
  renderWorkspaceSkills(packs, selected);
  const content = document.createDocumentFragment();
  if (!packs.length) {
    const empty = document.createElement("p");
    empty.className = "meta";
    empty.textContent = "No skills installed.";
    content.append(empty);
  }
  for (const pack of packs) {
    const group = document.createElement("details");
    group.className = "skill-pack";
    const summary = document.createElement("summary");
    summary.textContent = `${pack.name} · ${pack.source_format} · ${pack.skills.length} skills`;
    const packBody = document.createElement("div");
    packBody.className = "skill-pack-body";
    const heading = document.createElement("strong");
    heading.textContent = "Pack controls";
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
    packHead.append(heading, rename); packBody.append(packHead);
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
      packBody.append(row);
    }
    group.append(summary, packBody);
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

async function previewGithubSkill() {
  const url = elements.skillGithubUrl.value.trim();
  if (!url) return showError("Enter a GitHub SKILL.md or skill-folder URL");
  githubSkillPreviewId = null;
  elements.skillGithubPreview.disabled = true;
  elements.skillGithubInstall.disabled = true;
  elements.skillGithubStatus.textContent = "Resolving GitHub repository and creating an immutable preview...";
  try {
    const response = await fetch("/api/skills/github/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Unable to preview GitHub skill");
    githubSkillPreviewId = payload.preview_id;
    const skills = payload.pack?.skills || [];
    elements.skillEditor.value = skills.map((skill) => `# ${skill.name}\n${skill.content}`).join("\n\n---\n\n");
    elements.skillEditor.disabled = false;
    elements.skillGithubInstall.disabled = false;
    elements.skillGithubStatus.textContent = `Resolved commit ${payload.revision.slice(0, 12)} · ${payload.repository}/${payload.source_path} · ${skills.length} skill(s) ready to install`;
  } finally {
    elements.skillGithubPreview.disabled = false;
  }
}

async function installGithubSkill() {
  if (!githubSkillPreviewId) return showError("Preview the GitHub skill before installing it");
  elements.skillGithubInstall.disabled = true;
  elements.skillGithubStatus.textContent = "Installing reviewed GitHub skill...";
  const response = await fetch("/api/skills/github/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preview_id: githubSkillPreviewId }),
  });
  const payload = await response.json();
  if (!response.ok) {
    elements.skillGithubInstall.disabled = false;
    throw new Error(payload.detail || "Unable to install GitHub skill");
  }
  githubSkillPreviewId = null;
  skillsChangeRevision += 1;
  elements.skillGithubStatus.textContent = `Installed ${payload.name} with ${payload.skills.length} enabled skill(s)`;
  await Promise.all([loadSkills(), loadSkillsets()]);
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
    if (file.webkitRelativePath) body.append("relative_path", file.webkitRelativePath);
    const response = await fetch(`/api/sessions/${sessionId}/attachments`, { method: "POST", body });
    if (!response.ok) showError((await response.json()).detail || `Unable to import ${file.name}`);
  }
  await loadAttachments();
}

async function uploadSkillFolder(files) {
  if (!files.length) return;
  const body = new FormData();
  for (const file of files) {
    body.append("relative_paths", file.webkitRelativePath || file.name);
    body.append("files", file, file.name);
  }
  const response = await fetch("/api/skills/scan-upload", { method: "POST", body });
  const payload = await response.json();
  if (!response.ok) return showError(payload.detail || "Skill folder scan failed");
  renderSkillDiscoveries(payload);
}

function selectedModel() {
  return models.find((model) => model.name === elements.model.value);
}

function updateModelDetail() {
  const model = selectedModel();
  if (!model) {
    elements.modelDetail.textContent = elements.model.value === "multi-model"
      ? "Runs one durable, normalized result for every installed model."
      : "Automatically selects a compatible installed local model.";
    return;
  }
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
    elements.model.innerHTML = '<option value="auto">Auto</option><option value="multi-model">Multi-model</option>';
    elements.workspaceModel.innerHTML = "";
    for (const model of models) {
      const option = document.createElement("option");
      option.value = model.name;
      option.textContent = `${model.name}${model.installed ? "" : " — not installed"}`;
      option.disabled = !model.installed;
      elements.model.append(option);
      if (model.installed) {
        elements.workspaceModel.append(option.cloneNode(true));
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

function markOllamaReady() {
  elements.health.className = "health ready";
  elements.health.lastElementChild.textContent = "Ollama ready";
}

function showError(message) {
  elements.empty.hidden = true;
  elements.result.hidden = true;
  elements.error.hidden = false;
  elements.error.textContent = message;
}

async function responseErrorMessage(response, fallback) {
  const body = await response.text();
  if (!body.trim()) return fallback;
  try {
    return JSON.parse(body).detail || fallback;
  } catch (_error) {
    return body.trim();
  }
}

async function submitPrompt(event) {
  event.preventDefault();
  const prompt = elements.prompt.value.trim();
  if (!prompt) {
    showError("Enter a prompt before running the model.");
    elements.prompt.focus();
    return;
  }
  await ensureSession();
  setPending(true);
  elements.error.hidden = true;
  try {
    const attachmentIds = [...elements.attachmentList.querySelectorAll("[data-attachment-id]")].map((item) => item.dataset.attachmentId);
    const userMessage = await conversationView.appendUser(prompt, attachmentIds);
    elements.empty.hidden = true;
    elements.prompt.value = "";
    const response = await fetch("/api/workspace/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_root: elements.workspaceProjectRoot.value || ".",
        session_id: sessionId,
        engine_id: elements.workspaceAgentSelect.value,
        model_selection: elements.model.value,
        prompt,
        context_references: attachmentIds,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Workspace task failed");
    if (activeCoreTaskId !== payload.task_id) {
      activePlanReview = null;
      elements.taskPlanReviewOpen.hidden = true;
      if (elements.taskPlanReview.matches(":popover-open")) elements.taskPlanReview.hidePopover();
    }
    activeCoreTaskId = payload.task_id;
    activeWorkspaceRoute = payload.route;
    elements.taskRequestedModel.textContent = payload.requested_model;
    elements.taskEffectiveModel.textContent = payload.effective_model || "All installed models";
    elements.responseModel.textContent = payload.effective_model || payload.route;
    elements.summary.textContent = payload.status === "running" ? "Multi-model run started" : "Workspace task completed";
    elements.content.textContent = JSON.stringify({
      requested_engine: payload.requested_engine,
      effective_engine: payload.effective_engine,
      requested_model: payload.requested_model,
      effective_model: payload.effective_model,
      route: payload.route,
      warnings: payload.warnings,
      result: payload.result,
    }, null, 2);
    elements.result.hidden = false;
    renderWorkspaceActivityNotice(`${payload.route} · ${payload.status}`, payload.status);
    if (payload.route === "multi-model") localStorage.setItem("json_codr_active_model_run", payload.task_id);
    void userMessage;
    setPending(false);
    elements.cancel.hidden = payload.route !== "multi-model";
  } catch (error) {
    showError(error.message);
    setPending(false);
  }
}

elements.form.addEventListener("submit", submitPrompt);
elements.cancel.addEventListener("click", () => {
  if (!activeCoreTaskId) return;
  if (activeWorkspaceRoute === "multi-model") {
    fetch(`/api/model-runs/${encodeURIComponent(activeCoreTaskId)}/cancel`, { method: "POST" })
      .then((response) => { if (!response.ok) throw new Error("Unable to cancel multi-model run"); elements.cancel.hidden = true; })
      .catch((error) => showError(error.message));
    return;
  }
  coreClient.cancel(activeCoreTaskId).catch((error) => showError(error.message));
});
elements.model.addEventListener("change", updateModelDetail);
elements.prompt.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") elements.form.requestSubmit();
});
elements.form.addEventListener("dragover", (event) => event.preventDefault());
elements.form.addEventListener("drop", (event) => {
  event.preventDefault();
  if (event.dataTransfer?.files?.length) uploadFiles(event.dataTransfer.files).catch((error) => showError(error.message));
});
elements.taskSteer.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !activeCoreTaskId || !elements.taskSteer.value.trim()) return;
  event.preventDefault();
  const input = elements.taskSteer.value.trim();
  elements.taskSteer.value = "";
  coreClient.steer(activeCoreTaskId, input).catch((error) => showError(error.message));
});
elements.taskStop.addEventListener("click", () => {
  if (activeCoreTaskId) coreClient.cancel(activeCoreTaskId).catch((error) => showError(error.message));
});
elements.taskRetry.addEventListener("click", async () => {
  if (!activeCoreTaskId) return;
  try {
    const record = await coreClient.retry(activeCoreTaskId);
    activeCoreTaskId = record.task_id;
    taskView.render(record);
  } catch (error) { showError(error.message); }
});
elements.taskUndo.addEventListener("click", () => {
  if (!activeCoreTaskId) return;
  const record = coreClient.tasks.get(activeCoreTaskId)?.record;
  const checkpoint = [...(record?.events || [])].reverse().find((event) => event.payload?.checkpoint_id)?.payload.checkpoint_id;
  if (!checkpoint) return showError("No checkpoint is available for this task.");
  coreClient.restore(activeCoreTaskId, checkpoint).catch((error) => showError(error.message));
});
elements.taskPlanApprove.addEventListener("click", () => submitPlanReview("approve").catch((error) => showError(error.message)));
elements.taskPlanEdit.addEventListener("click", () => submitPlanReview("edit").catch((error) => showError(error.message)));
elements.taskPlanRequestChanges.addEventListener("click", () => submitPlanReview("request_changes").catch((error) => showError(error.message)));
elements.taskPlanReject.addEventListener("click", () => submitPlanReview("reject").catch((error) => showError(error.message)));
elements.taskPlanReviewOpen.addEventListener("click", () => {
  elements.taskPlanReview.showPopover();
  elements.taskPlanCanonical.focus({ preventScroll: true });
});
elements.taskPlanReview.addEventListener("toggle", () => {
  elements.taskPlanReviewOpen.setAttribute(
    "aria-expanded",
    String(elements.taskPlanReview.matches(":popover-open")),
  );
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.taskPlanReview.matches(":popover-open")) {
    elements.taskPlanReview.hidePopover();
    elements.taskPlanReviewOpen.focus();
  }
});
elements.taskStepEdit.addEventListener("click", () => submitStepReview("edit").catch((error) => showError(error.message)));
elements.taskStepRequestChanges.addEventListener("click", () => submitStepReview("request_changes").catch((error) => showError(error.message)));
elements.taskStepReject.addEventListener("click", () => submitStepReview("reject").catch((error) => showError(error.message)));
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
    headers: window.JSONCodrHttpIdentity.mutationHeaders({ "Content-Type": "application/json" }),
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
elements.workspaceLayoutMenu.addEventListener("click", () => {
  const opening = elements.workspaceLayoutPopover.hidden;
  elements.workspaceLayoutPopover.hidden = !opening;
  elements.workspaceLayoutMenu.setAttribute("aria-expanded", String(opening));
  if (opening) elements.workspaceLayoutPopover.querySelector("button")?.focus();
});
elements.workspaceLayoutPopover.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const state = button.dataset.workspaceAction === "reset"
    ? workspaceLayout.reset()
    : workspaceLayout.applyPreset(button.dataset.workspacePreset);
  renderWorkspaceLayout(state);
  elements.workspaceLayoutPopover.hidden = true;
  elements.workspaceLayoutMenu.setAttribute("aria-expanded", "false");
  elements.workspaceLayoutMenu.focus();
});
for (const separator of elements.workspaceSeparators) bindWorkspaceSeparator(separator);
const applyWorkspaceViewport = () => renderWorkspaceLayout(workspaceLayout.applyViewport(window.innerWidth));
window.addEventListener("resize", applyWorkspaceViewport);
document.addEventListener("keydown", (event) => {
  if (!event.altKey || event.ctrlKey || event.metaKey) return;
  const region = event.key === "1" ? "left" : event.key === "2" ? "bottom" : event.key === "3" ? "right" : null;
  if (!region) return;
  event.preventDefault();
  focusWorkspaceRegion(region);
});
// Discoverable labels for the direct region shortcuts: Alt+1, Alt+2, Alt+3.
for (const button of elements.hardwareSectionButtons) {
  button.addEventListener("click", () => selectHardwareSection(button.dataset.hardwareSection));
}

function identityCsrfToken() {
  const item = document.cookie.split("; ").find((value) => value.startsWith("json_codr_csrf=") || value.startsWith("__Host-json_codr_csrf="));
  return item ? decodeURIComponent(item.slice(item.indexOf("=") + 1)) : "";
}

async function loadIdentityAccess() {
  const bootstrap = await fetch("/api/identity/bootstrap").then((response) => response.json());
  elements.identityDevelopmentWarning.hidden = !bootstrap.development_bypass?.enabled;
  const accountResponse = await fetch("/api/identity/account");
  const signedIn = accountResponse.ok;
  elements.identityLoginForm.hidden = signedIn;
  elements.identityAccountPanel.hidden = !signedIn;
  elements.identitySessionStatus.textContent = signedIn ? "Signed in" : "Signed out";
  if (!signedIn) return;
  const account = await accountResponse.json();
  elements.identityAccountName.textContent = account.display_name;
  elements.identityAccountRoles.textContent = account.roles.join(" · ");
  const usersResponse = await fetch("/api/identity/users");
  if (!usersResponse.ok) return;
  const users = await usersResponse.json();
  elements.identityUsers.replaceChildren(...users.users.map((user) => {
    const card = document.createElement("article");
    card.className = "identity-user-card";
    const name = document.createElement("strong");
    name.textContent = user.display_name;
    const details = document.createElement("p");
    details.className = "meta";
    details.textContent = `${user.username} · ${user.roles.join(", ")} · ${user.status}`;
    card.append(name, details);
    return card;
  }));
}
for (const button of elements.settingsSectionButtons) {
  button.addEventListener("click", () => {
    selectSettingsSection(button.dataset.settingsSection, { focus: true });
    if (button.dataset.settingsSection === "access") loadIdentityAccess().catch((error) => { elements.identityStatus.textContent = error.message; });
  });
}

elements.identityLoginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.identityStatus.textContent = "Signing in…";
  try {
    await fetch("/api/identity/bootstrap");
    const response = await fetch("/api/identity/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": identityCsrfToken() },
      body: JSON.stringify({ username: elements.identityUsername.value, password: elements.identityPassword.value }),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "Unable to sign in");
    elements.identityPassword.value = "";
    elements.identityStatus.textContent = "Signed in";
    await loadIdentityAccess();
  } catch (error) {
    elements.identityStatus.textContent = error.message;
  }
});

elements.identityLogout?.addEventListener("click", async () => {
  const response = await fetch("/api/identity/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": identityCsrfToken() },
  });
  if (!response.ok) {
    elements.identityStatus.textContent = (await response.json()).detail || "Unable to sign out";
    return;
  }
  elements.identityStatus.textContent = "Signed out";
  await loadIdentityAccess();
});
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
elements.memorySettingsSave.addEventListener("click", async () => {
  elements.memorySettingsSave.disabled = true;
  elements.memorySettingsStatus.textContent = "Saving…";
  try {
    await saveSettings({ memory: {
      enabled: elements.memoryEnabled.checked,
      detailed_retention_enabled: elements.memoryDetailedRetention.checked,
      search_limit: Number(elements.memorySearchLimit.value),
    } });
    elements.memorySettingsStatus.textContent = "Memory settings saved";
  } catch (error) {
    elements.memorySettingsStatus.textContent = error.message;
  } finally {
    elements.memorySettingsSave.disabled = false;
  }
});
elements.uiSave.addEventListener("click", async () => {
  const revision = ++themeSaveRevision;
  const nextThemeMode = uiCustomizationController.getState().mode;
  try {
    await saveSettings({ ui: { theme: nextThemeMode } });
  } catch (error) {
    if (revision === themeSaveRevision) {
      elements.uiPreviewStatus.textContent = "Appearance saved locally; server preference could not be updated.";
    }
    showError(error.message);
  }
});
elements.attachmentInput.addEventListener("change", async () => {
  try {
    await uploadFiles(elements.attachmentInput.files);
  } finally {
    elements.attachmentInput.value = "";
  }
});
elements.workspaceAttach.addEventListener("click", () => {
  if (elements.workspaceFilesPopover.matches(":popover-open")) {
    closeWorkspaceFilesPopover();
  } else {
    elements.workspaceFilesPopover.showPopover();
    positionWorkspaceFilesPopover();
  }
});
elements.workspaceFilesPopover.addEventListener("toggle", () => {
  elements.workspaceAttach.setAttribute(
    "aria-expanded",
    String(elements.workspaceFilesPopover.matches(":popover-open")),
  );
});
elements.workspaceFilesManage.addEventListener("click", () => {
 closeWorkspaceFilesPopover();
 selectDestination("context");
});
elements.workspaceFilesAttach.addEventListener("click", () => {
 closeWorkspaceFilesPopover();
 elements.attachmentInput.click();
});
document.addEventListener("click", (event) => {
  if (!elements.workspaceAttachmentMenu.contains(event.target)) closeWorkspaceFilesPopover();
});
window.addEventListener("resize", positionWorkspaceFilesPopover);
window.addEventListener("scroll", positionWorkspaceFilesPopover, true);
elements.attachmentFolderInput.addEventListener("change", async () => {
  try {
    await uploadFiles(elements.attachmentFolderInput.files);
  } finally {
    elements.attachmentFolderInput.value = "";
  }
});
elements.pasteTextButton.addEventListener("click", async () => {
  await ensureSession();
  const text = await navigator.clipboard.readText();
  if (!text.trim()) return;
  await fetch(`/api/sessions/${sessionId}/clipboard-text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  await loadAttachments();
});
elements.scanDependencies.addEventListener("click", () => loadDependencies().catch((error) => showError(error.message)));
elements.skillScan.addEventListener("click", () => scanSkillDirectory().catch((error) => showError(error.message)));
elements.skillGithubPreview.addEventListener("click", () => previewGithubSkill().catch((error) => {
  elements.skillGithubStatus.textContent = error.message;
  showError(error.message);
}));
elements.skillGithubInstall.addEventListener("click", () => installGithubSkill().catch((error) => {
  elements.skillGithubStatus.textContent = error.message;
  showError(error.message);
}));
elements.skillFolderInput.addEventListener("change", async () => {
  try {
    await uploadSkillFolder(elements.skillFolderInput.files);
  } catch (error) {
    showError(error.message);
  } finally {
    elements.skillFolderInput.value = "";
  }
});
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
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    event.preventDefault();
    elements.terminalInput.value = terminalKeyboardController?.navigateHistory(
      event.key === "ArrowUp" ? -1 : 1,
      elements.terminalInput.value,
    ) || "";
  }
});
elements.terminalStop.addEventListener("click", () => {
  if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(JSON.stringify({ type: "interrupt" }));
});
elements.workspaceTabs.forEach((tab) => tab.addEventListener("click", async () => {
  selectWorkspaceMode(tab.dataset.workspaceMode);
  if (activeWorkspaceMode !== "shell") return;
  const session = terminalSessions.get(activeTerminalProfile);
  if (session?.terminal) await connectTerminalRecord(session.terminal);
  else await ensureTerminal();
}));
elements.workspaceAgentForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runWorkspaceAgent();
});
elements.workspaceAgentApprove.addEventListener("click", approveWorkspaceAgentAction);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.workspaceFilesPopover.matches(":popover-open")) {
    event.preventDefault();
    closeWorkspaceFilesPopover({ restoreFocus: true });
  }
  if (event.ctrlKey && !event.altKey && event.key.toLowerCase() === "j") {
    event.preventDefault();
    selectDestination("workspace");
    openWorkspacePanel("terminal", "bottom");
  }
  if (event.ctrlKey && event.altKey && event.key.toLowerCase() === "b") {
    event.preventDefault();
    selectDestination("context");
  }
  if (event.key === "Escape" && document.body.classList.contains("navigation-open")) {
    closeNavigationDrawer({ restoreFocus: true });
  }
});
registerWorkspacePanel({
  id: "files",
  element: elements.workspaceFilesPanel,
  allowedPlacements: ["left", "right", "bottom"],
  managementDestination: "context",
});
registerWorkspacePanel({
  id: "skills",
  element: elements.workspaceSkillsPanel,
  allowedPlacements: ["left", "right", "bottom"],
  managementDestination: "skills",
});
registerWorkspacePanel({
  id: "activity",
  element: elements.workspaceActivityPanel,
  allowedPlacements: ["right", "left", "bottom"],
});
registerWorkspacePanel({
  id: "terminal",
  element: elements.terminalPanel,
  allowedPlacements: ["bottom", "left", "right"],
  onShown: () => {
    initializeXterm();
    requestAnimationFrame(() => terminalFitAddon?.fit());
  },
});
document.querySelector("#workspace-dock-files-attach")?.addEventListener("click", () => elements.attachmentInput.click());
for (const button of document.querySelectorAll("[data-manage-destination]")) {
  button.addEventListener("click", () => selectDestination(button.dataset.manageDestination));
}
applyWorkspaceViewport();
initializeXterm();
elements.workspaceProjectRoot.value = localStorage.getItem("json_codr_workspace_project_root") || ".";
window.addEventListener("beforeunload", persistTerminalSessions);
restoreTerminalSessions().catch(() => localStorage.removeItem(TERMINAL_SESSIONS_KEY));
loadApplication().then(() => queueSettingsLoad()).then(() => loadComponents()).catch((error) => showError(error.message));
loadHardwareStatus().catch((error) => showError(error.message));
loadAttachments().catch((error) => showError(error.message));
loadSkillsets().catch((error) => showError(error.message));

let pendingComponentPlan = null;
async function loadComponents() {
  const container = document.querySelector("#component-list");
  if (!container) return;
  const installedComponents = await coreClient.listComponents("");
  const unavailableModels = models.filter((model) => !model.installed).map((model) => ({
    component_id: model.name,
    name: model.name,
    available: false,
    reason: "Model is configured but not installed in Ollama.",
    statusSource: "Ollama model roster",
    destination: "hardware",
  }));
  const components = [
    ...installedComponents.map((component) => ({ ...component, available: component.state !== "quarantined", statusSource: "BORG component registry" })),
    ...unavailableModels,
  ];
  renderDisabledComponents(components);
  const activePanels = new Set(getActiveWorkspacePanels(components));
  for (const [panelId, panel] of workspacePanels) {
    if (!activePanels.has(panelId)) panel.element.hidden = true;
  }
  container.replaceChildren();
  if (!installedComponents.length) {
    const empty = document.createElement("p"); empty.className = "meta"; empty.textContent = "No verified components loaded."; container.append(empty); return;
  }
  installedComponents.forEach((component) => {
    const row = document.createElement("article"); row.className = "dependency-item";
    const title = document.createElement("strong"); title.textContent = component.component_id;
    const detail = document.createElement("p"); detail.className = "meta"; detail.textContent = `${component.runtime_kind} · generation ${component.generation} · verified brokered capability`;
    row.append(title, detail); container.append(row);
  });
}
const componentPlanButton = document.querySelector("#component-plan");
const componentInstallButton = document.querySelector("#component-install");
componentPlanButton?.addEventListener("click", async () => {
  const source = document.querySelector("#component-source").value.trim();
  const scope = document.querySelector("#component-scope").value;
  if (!source) return showError("Enter a component source first");
  pendingComponentPlan = await coreClient.planComponent({
    source_kind: document.querySelector("#component-source-kind").value, source, scope,
    project_id: scope === "project" ? `project-${sessionId}` : null, activation: true,
  });
  const details = document.querySelector("#component-plan-details"); details.hidden = false;
  details.textContent = JSON.stringify({ component_id: pendingComponentPlan.component_id, runtime: pendingComponentPlan.runtime_kind, executable: pendingComponentPlan.executable, entry_points: pendingComponentPlan.entry_points, effects: pendingComponentPlan.effects, normalization: pendingComponentPlan.normalization }, null, 2);
  componentInstallButton.disabled = false;
});
componentInstallButton?.addEventListener("click", async () => {
  if (!pendingComponentPlan) return;
  componentInstallButton.disabled = true;
  const result = await coreClient.installComponent(pendingComponentPlan.plan_id, pendingComponentPlan.approval_digest);
  document.querySelector("#component-plan-details").textContent = JSON.stringify(result, null, 2);
  pendingComponentPlan = null;
  await loadComponents();
});
elements.workspaceActivityStop?.addEventListener("click", () => elements.taskStop.click());
