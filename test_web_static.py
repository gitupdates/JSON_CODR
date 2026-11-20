import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app


class FakeService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []

    async def generate_deterministic(self, model, messages, temperature=0.0):
        return ""


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])


class WebStaticTests(unittest.TestCase):
    def test_all_model_search_is_additive_and_exposes_jury_controls(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        runtime = Path("web/model_runs.js").read_text(encoding="utf-8") if Path("web/model_runs.js").exists() else ""
        for identifier in (
            "chat-form", "model-select", "all-model-form", "all-model-prompt", "all-model-profile",
            "all-model-start", "all-model-cancel", "all-model-status", "all-model-filter",
            "all-model-results", "all-model-consensus", "all-model-export-json",
            "all-model-export-markdown", "all-model-export-csv",
        ):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn("General search", html)
        self.assertIn("Code jury", html)
        self.assertIn("/api/model-runs", runtime)
        self.assertIn("original", runtime)
        self.assertIn("setTimeout", runtime)
        self.assertIn("pollInFlight", runtime)
        self.assertIn("data-result-id", runtime)
        self.assertIn("terminalStatuses", runtime)
        self.assertIn('"X-JSON-CODR": "1"', runtime)
        self.assertIn("preventDefault", runtime)
        self.assertIn("json_codr_active_model_run", runtime)
        self.assertIn("original-output-raw", runtime)

    def test_unified_runtime_replaces_executor_specific_profiles(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        script = Path("web/app.js").read_text(encoding="utf-8")

        self.assertNotIn('id="coding-agent-tool"', html)
        self.assertNotIn('/api/git-broker/adapter', script)
        self.assertIn("JSONCodrCoreClient", script)
        self.assertIn("normalizeTerminalOutput", script)
    def test_unified_task_view_is_additive_to_live_cli(self):
        html = self.client.get("/").text
        self.assertIn('id="task-activity"', html)
        self.assertIn('id="terminal-input"', html)
        script = self.client.get("/static/app.js").text
        self.assertIn("closeActiveTerminal", script)
        self.assertIn('method: "DELETE"', script)
        self.assertIn("terminal.external", script)
        self.assertIn("JSONCodrTaskView", script)

    def test_project_workspace_exposes_shell_and_agent_without_provider_tabs(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text
        parser = IdCollector()
        parser.feed(html)

        self.assertTrue({
            "workspace-shell", "workspace-agent", "workspace-project-root",
            "workspace-model", "workspace-outcome", "workspace-agent-run",
            "workspace-agent-status", "workspace-agent-result",
        }.issubset(parser.ids))
        self.assertIn('data-workspace-mode="shell"', html)
        self.assertIn('data-workspace-mode="agent"', html)
        self.assertNotIn('data-workspace-mode="codex"', html)
        self.assertIn("function selectWorkspaceMode", script)
        self.assertIn('fetch("/api/workspace/tasks"', script)
        self.assertIn('"X-JSON-CODR": "1"', script)
        self.assertIn("requested_model", script)
        self.assertIn("effective_model", script)

    def test_unified_workspace_exposes_semantic_regions_and_primary_controls(self):
        html = self.client.get("/").text
        parser = IdCollector()
        parser.feed(html)

        self.assertTrue({
            "workspace-header", "workspace-left-dock", "workspace-task-canvas",
            "workspace-right-dock", "workspace-bottom-dock", "workspace-statusbar",
            "workspace-agent-select", "model-select", "workspace-layout-menu",
            "workspace-attach", "submit-button",
        }.issubset(parser.ids))
        self.assertIn('role="tablist" aria-label="Task views"', html)
        self.assertGreaterEqual(html.count('role="separator"'), 3)
        self.assertIn('aria-orientation="vertical"', html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn('aria-label="Attach files"', html)
        self.assertIn('<span>Run</span>', html)
        self.assertNotIn('Agent Activity', html)

    def test_workspace_panel_registry_uses_single_instance_layout_transitions(self):
        script = self.client.get("/static/app.js").text
        html = self.client.get("/").text

        for contract in (
            "workspacePanels = new Map", "registerWorkspacePanel", "renderWorkspaceLayout",
            "openWorkspacePanel", "focusWorkspaceRegion", "setPointerCapture",
            "workspaceLayout.resize", "workspaceLayout.reset",
        ):
            self.assertIn(contract, script)
        self.assertIn("workspacePanels.has(id)", script)
        self.assertIn("host.append(panel.element)", script)
        self.assertIn('id="workspace-layout-popover"', html)
        self.assertIn('data-workspace-preset="focus"', html)
        self.assertIn('data-workspace-action="reset"', html)

    def test_terminal_is_registered_once_as_a_persistent_workspace_panel(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text

        self.assertEqual(html.count('id="terminal-panel"'), 1)
        self.assertIn('id="terminal-panel" class="terminal-panel"', html)
        self.assertIn('registerWorkspacePanel({', script)
        self.assertIn('id: "terminal"', script)
        self.assertIn('onShown: () =>', script)
        self.assertIn('openWorkspacePanel("terminal", "bottom")', script)

    def test_task_context_panels_reuse_existing_state_and_link_to_management(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text

        for identifier in (
            "workspace-files-panel", "workspace-files-list", "workspace-files-attach",
            "workspace-skills-panel", "workspace-skills-list",
            "workspace-activity-panel", "workspace-activity-notice",
        ):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn('data-manage-destination="context"', html)
        self.assertIn('data-manage-destination="skills"', html)
        for panel_id in ("files", "skills", "activity"):
            self.assertIn(f'id: "{panel_id}"', script)
        self.assertIn("renderWorkspaceFiles", script)
        self.assertIn("renderWorkspaceSkills", script)
        self.assertIn("saveSkillSelection(selected)", script)
        self.assertIn("renderWorkspaceActivityNotice", script)
        self.assertNotIn('onShown: () => loadAttachments()', script)
        self.assertNotIn('onShown: () => loadSkills()', script)

    def test_disabled_components_are_settings_only_and_workspace_panels_are_filtered(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text

        self.assertIn('id="disabled-components"', html)
        self.assertIn("function getActiveWorkspacePanels", script)
        self.assertIn("function renderDisabledComponents", script)
        self.assertIn("unavailableReason", script)
        self.assertIn("statusSource", script)
        self.assertIn("Enable or configure", script)
        self.assertIn("getActiveWorkspacePanels(components)", script)

    def test_workspace_header_submits_canonical_engine_and_model_selection(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text

        self.assertIn('id="workspace-agent-select"', html)
        self.assertNotIn('id="workspace-agent-select" disabled', html)
        self.assertIn('value="borg"', html)
        self.assertIn('value="auto"', html)
        self.assertIn('value="multi-model"', html)
        self.assertIn('fetch("/api/workspace/tasks"', script)
        self.assertIn("requested_engine", script)
        self.assertIn("effective_engine", script)
        self.assertIn("requested_model", script)
        self.assertIn("effective_model", script)
        self.assertIn('`/api/model-runs/${encodeURIComponent(activeCoreTaskId)}/cancel`', script)
        self.assertNotIn('fetch("/api/project-workspace/run"', script)

    def test_plain_text_api_failures_are_rendered_without_json_parse_errors(self):
        script = self.client.get("/static/app.js").text

        self.assertIn("async function responseErrorMessage", script)
        self.assertIn('responseErrorMessage(response, "Hardware detection failed")', script)

    def test_runtime_observability_is_progressive_not_a_new_destination(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text
        self.assertIn('id="runtime-diagnostics"', html)
        self.assertIn('id="workspace-activity-panel"', html)
        self.assertIn('/api/runtime/status', script)
        self.assertNotIn('data-destination="runtime"', html)

    def test_new_terminal_process_resets_the_replay_cursor(self):
        script = self.client.get("/static/app.js").text

        self.assertIn("storedSession.terminal?.id !== terminal.id", script)
        self.assertIn("storedSession.lastSequence = 0", script)

    def setUp(self):
        self.client = TestClient(create_app(FakeService()))

    def test_root_serves_the_complete_chat_interface(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("V1.0.18-alpha.16", response.text)
        parser = IdCollector()
        parser.feed(response.text)
        self.assertTrue(
            {
                "health-status",
                "model-select",
                "prompt-input",
                "submit-button",
                "cancel-button",
                "summary-output",
                "content-output",
                "artifact-output",
                "error-output",
                "conversation-timeline",
                "conversation-export-markdown",
                "conversation-export-json",
                "conversation-export-zip",
            }.issubset(parser.ids)
        )

    def test_static_assets_are_served_with_correct_types(self):
        html = self.client.get("/").text
        css = self.client.get("/static/app.css")
        javascript = self.client.get("/static/app.js")
        self.assertIn('/static/app.css?v=1.0.18-alpha.16', html)
        self.assertEqual(css.status_code, 200)
        self.assertIn("text/css", css.headers["content-type"])
        self.assertEqual(javascript.status_code, 200)
        self.assertIn("javascript", javascript.headers["content-type"])

    def test_workspace_layout_controller_loads_before_application(self):
        html = self.client.get("/").text

        layout_index = html.index('/static/workspace_layout.js')
        application_index = html.index('/static/app.js')
        self.assertLess(layout_index, application_index)
        self.assertIn('json_codr_workspace_layout_v1', Path("web/workspace_layout.js").read_text(encoding="utf-8"))

    def test_global_navigation_and_hardware_sections_are_present(self):
        html = self.client.get("/").text
        parser = IdCollector()
        parser.feed(html)

        self.assertTrue({
            "app-sidebar", "sidebar-collapse", "sidebar-resize-handle",
            "mobile-navigation-toggle", "navigation-backdrop",
            "view-chat", "terminal-panel", "context-panel", "skills-panel",
            "hardware-panel", "settings-panel",
        }.issubset(parser.ids))
        for destination in ("workspace", "context", "skills", "hardware", "settings"):
            self.assertIn(f'data-destination="{destination}"', html)
        self.assertNotIn('data-destination="chat"', html)
        self.assertNotIn('data-destination="terminal"', html)
        for section in (
            "overview", "profiles", "runtimes", "compatibility", "model-search",
            "benchmarks", "history", "localperf",
        ):
            self.assertIn(f'data-hardware-section="{section}"', html)
            self.assertIn(f'data-hardware-view="{section}"', html)
        self.assertIn('role="separator"', html)
        self.assertIn('aria-valuemin="220"', html)
        self.assertIn('aria-valuemax="380"', html)
        self.assertIn('class="nav-icon"', html)
        self.assertIn('stroke="currentColor"', html)
        self.assertIn('id="terminal-panel"', html)
        self.assertIn('id="hardware-benchmark-run"', html)
        self.assertNotIn('role="tablist" aria-label="Hardware settings"', html)
        self.assertNotIn('id="hardware-tab-optimization"', html)
        self.assertNotIn('id="hardware-tab-benchmarks"', html)

    def test_global_navigation_runtime_contracts_are_present(self):
        javascript = self.client.get("/static/app.js").text

        self.assertIn("const NAVIGATION_DESTINATIONS", javascript)
        self.assertIn("const HARDWARE_SECTIONS", javascript)
        self.assertIn("function selectDestination(destination", javascript)
        self.assertIn("function selectHardwareSection(section", javascript)
        self.assertIn("function setSidebarCollapsed(collapsed", javascript)
        self.assertIn("primary_destination: destination", javascript)
        self.assertIn("hardware_section: section", javascript)
        self.assertIn("sidebar_collapsed: collapsed", javascript)
        self.assertIn("sidebar_width: width", javascript)
        self.assertIn("Math.max(220, Math.min(380", javascript)
        self.assertIn('addEventListener("pointerup"', javascript)
        self.assertIn('key === "ArrowLeft"', javascript)
        self.assertIn('key === "ArrowRight"', javascript)
        self.assertIn("requestAnimationFrame", javascript)
        self.assertIn("closeNavigationDrawer", javascript)
        self.assertIn("mobileNavigationToggle.focus()", javascript)
        self.assertIn('selectDestination("terminal"', javascript)
        self.assertIn('selectDestination("context"', javascript)
        self.assertIn("view.hidden = view.dataset.view !== destination", javascript)

    def test_attachment_context_tray_controls_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertTrue(
            {
                "context-panel",
                "attachment-input",
                "paste-text-button",
                "attachment-list",
                "attachment-preview",
            }.issubset(parser.ids)
        )
        javascript = self.client.get("/static/app.js").text
        self.assertIn("/api/sessions", javascript)
        self.assertIn("navigator.clipboard", javascript)
        self.assertIn("/original", javascript)
        self.assertIn("/retry", javascript)

    def test_native_file_and_folder_pickers_feed_existing_import_flows(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        self.assertIn('workspaceAttach: document.querySelector("#workspace-attach")', javascript)
        self.assertIn(
            'elements.workspaceAttach.addEventListener("click", () => elements.attachmentInput.click())',
            javascript,
        )
        self.assertIn('for="attachment-input">Browse files', html)
        self.assertIn('id="attachment-folder-input"', html)
        self.assertIn('id="skill-folder-input"', html)
        self.assertEqual(html.count("webkitdirectory"), 2)
        self.assertIn("attachmentFolderInput", javascript)
        self.assertIn("skillFolderInput", javascript)
        self.assertIn("file.webkitRelativePath || file.name", javascript)
        self.assertIn('/api/skills/scan-upload', javascript)
        self.assertIn("renderSkillDiscoveries(payload)", javascript)
        self.assertIn('elements.attachmentFolderInput.value = ""', javascript)
        self.assertIn('elements.skillFolderInput.value = ""', javascript)

    def test_live_cli_bottom_panel_controls_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertTrue(
            {
                "terminal-panel",
                "terminal-output",
                "terminal-input",
                "terminal-run",
                "terminal-stop",
            }.issubset(parser.ids)
        )
        javascript = self.client.get("/static/app.js").text
        self.assertIn("/api/terminals", javascript)
        self.assertIn("/ws/terminals/", javascript)

    def test_embedded_conpty_terminal_has_xterm_tabs_resize_and_reconnect(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        self.assertIn('/static/vendor/xterm.css', html)
        self.assertIn('/static/vendor/xterm.js', html)
        self.assertIn('/static/vendor/xterm-addon-fit.js', html)
        self.assertIn('id="terminal-tabs"', html)
        self.assertIn('data-terminal-profile="powershell"', html)
        self.assertEqual(html.count('data-terminal-profile="powershell"'), 1)
        self.assertIn('id="terminal-xterm"', html)
        self.assertIn('type: "resize"', javascript)
        self.assertIn('type: "attach"', javascript)
        self.assertIn("lastTerminalSequence", javascript)
        self.assertIn('"json_codr_terminal_sessions"', javascript)
        self.assertIn("restoreTerminalSessions", javascript)

    def test_terminal_uses_global_clipboard_and_interrupt_chord(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        self.assertIn('/static/terminal_keyboard.js?v=1.0.18-alpha.16', html)
        self.assertIn('/static/app.js?v=1.0.18-alpha.16', html)
        self.assertLess(html.index("terminal_keyboard.js"), html.index("app.js"))
        self.assertIn("createTerminalKeyboardController", javascript)
        self.assertIn("attachCustomKeyEventHandler", javascript)
        self.assertIn("navigator.clipboard.writeText", javascript)
        self.assertIn('JSON.stringify({ type: "interrupt" })', javascript)
        self.assertIn("navigateHistory", javascript)
        self.assertIn('command === "clr --history"', javascript)
        self.assertIn('command === "clr --command"', javascript)

    def test_folder_attachment_upload_sends_relative_paths(self):
        javascript = self.client.get("/static/app.js").text

        self.assertIn('body.append("relative_path", file.webkitRelativePath)', javascript)

    def test_dependency_review_controls_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertTrue(
            {
                "dependency-review",
                "dependency-list",
                "scan-dependencies",
            }.issubset(parser.ids)
        )

    def test_automatic_dependencies_use_ordered_live_cli_queue(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        self.assertLess(
            html.index('/static/dependency_install_queue.js'),
            html.index('/static/app.js'),
        )
        self.assertIn("createDependencyInstallQueue(async (command)", javascript)
        self.assertIn("runTerminalCommand(command)", javascript)
        self.assertIn("suggestion.automatic", javascript)
        self.assertIn("dependencyInstallQueue.enqueue(suggestion.command)", javascript)
        self.assertIn('elements.terminalStatus.textContent = "Installing prerequisites..."', javascript)
        self.assertIn('addEventListener("error", onFailure', javascript)
        self.assertIn('addEventListener("close", onFailure', javascript)

    def test_dependency_preflight_runs_off_the_async_event_loop(self):
        application = Path(__file__).parent.joinpath("web_app", "app.py").read_text(encoding="utf-8")
        self.assertIn("await asyncio.to_thread(dependency_service.detect, session_id)", application)

    def test_skill_library_controls_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertNotIn("Â", response.text)
        self.assertIn("JSON_CODR skill authoring standard</a> &middot; <a", response.text)
        self.assertTrue(
            {
                "skills-panel",
                "settings-panel",
                "skill-library",
                "skill-list",
                "skill-details",
                "skill-preview",
                "skill-install",
                "skill-editor",
                "skill-save",
                "skill-remove-pack",
                "skill-scan-directory",
                "skill-scan",
                "skill-scan-results",
                "skill-scan-known",
                "approved-skill-directories",
            }.issubset(parser.ids)
        )
        self.assertIn("markOllamaReady();", self.client.get("/static/app.js").text)

    def test_github_skill_installer_controls_and_runtime_are_present(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        for identifier in ("skill-github-url", "skill-github-preview", "skill-github-install", "skill-github-status"):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn('/api/skills/github/preview', javascript)
        self.assertIn('/api/skills/github/install', javascript)
        self.assertIn("Resolved commit", javascript)


    def test_settings_is_a_global_navigation_destination(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text
        self.assertIn('data-destination="settings"', html)
        self.assertIn('data-view="settings"', html)
        self.assertIn("view.hidden = view.dataset.view !== destination", javascript)

    def test_hardware_optimization_controls_are_present(self):
        html = self.client.get("/").text
        parser = IdCollector()
        parser.feed(html)
        self.assertTrue({
            "hardware-status", "hardware-detect", "hardware-candidates", "hardware-restore-cpu"
        }.issubset(parser.ids))
        javascript = self.client.get("/static/app.js").text
        self.assertIn('fetch("/api/hardware/detect"', javascript)
        self.assertIn('fetch("/api/hardware/probe"', javascript)
        self.assertIn('fetch("/api/hardware/restore-cpu"', javascript)
        self.assertIn("OpenVINO", html)
        self.assertIn("Ryzen AI", html)
        self.assertIn("WinML", html)
        self.assertIn("DirectML", html)
        self.assertIn('fetch("/api/inference/catalog"', javascript)
        self.assertIn("install-proposal", javascript)
        self.assertIn("Review runtime install", javascript)
        self.assertIn("Driver guidance", javascript)

    def test_hardware_sections_run_fresh_scans_when_needed(self):
        javascript = self.client.get("/static/app.js").text.replace("\r\n", "\n")
        self.assertIn('section === "runtimes" || section === "compatibility" || section === "benchmarks"', javascript)
        self.assertIn('detectHardware().catch', javascript)
        self.assertIn('section === "overview"', javascript)
        self.assertIn('loadHardwareTelemetry().catch', javascript)
        self.assertIn("let hardwareDetectionPromise = null", javascript)

    def test_hardware_benchmark_tab_runs_suites_and_renders_cpu_relative_results(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        for identifier in (
            "hardware-panel", "hardware-benchmark-suite", "hardware-benchmark-model",
            "hardware-benchmark-backend",
            "hardware-benchmark-run", "hardware-benchmark-status", "hardware-benchmark-results",
            "hardware-benchmark-history", "hardware-benchmark-clear",
            "localperf-export", "localperf-include-details", "localperf-import",
            "localperf-import-input", "localperf-retain-details", "localperf-package-status",
            "optimized-model-search-provider", "optimized-model-search-query",
            "optimized-model-search-run", "optimized-model-search-results",
            "leaderboard-search", "leaderboard-model-filter", "leaderboard-backend-filter",
            "leaderboard-suite-filter", "leaderboard-metric", "leaderboard-kpis",
            "leaderboard-table", "leaderboard-backend-chart", "leaderboard-trend-chart",
            "leaderboard-details", "leaderboard-status",
        ):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn('data-hardware-section="benchmarks">Performance benchmarks', html)
        self.assertIn('data-hardware-section="leaderboard">Leaderboard', html)
        self.assertIn('data-hardware-view="benchmarks"', html)
        self.assertIn('data-hardware-view="leaderboard"', html)
        self.assertIn('data-hardware-view="history"', html)
        self.assertIn('data-hardware-view="localperf"', html)
        self.assertIn('fetch("/api/hardware/benchmarks"', javascript)
        self.assertIn("speedup_vs_cpu", javascript)
        self.assertIn("tokens_per_second", javascript)
        self.assertIn("result.tests", javascript)
        self.assertIn("backend: elements.hardwareBenchmarkBackend.value", javascript)
        self.assertIn("Running standardized benchmark", javascript)
        self.assertIn('fetch("/api/inference/environments")', javascript)
        self.assertIn("Selected for compatibility and performance", javascript)
        self.assertIn("Not eligible", javascript)
        self.assertIn("candidate.runnable === false", javascript)
        self.assertIn("candidate.readiness", javascript)
        self.assertIn("result.gpu_percent", javascript)
        self.assertIn("GPU offload verified", javascript)
        self.assertIn("0.3.0-localperf", html)
        self.assertIn("result.localperf", javascript)
        self.assertIn("ttft_ms", javascript)
        self.assertIn('method: "DELETE"', javascript)
        self.assertIn("/api/localperf/packages/", javascript)
        self.assertIn("/api/localperf/packages/preview", javascript)
        self.assertIn("/api/localperf/packages/import", javascript)
        self.assertIn("contains_system_details", javascript)
        self.assertIn('fetch("/api/hardware/detect", { method: "POST" })', javascript)
        self.assertIn("candidate.compatible_models", javascript)
        self.assertNotIn('fetch("/api/hardware/model-compatibility")', javascript)
        self.assertIn('/api/inference/models/search', javascript)
        self.assertIn('model.status === "accelerated"', javascript)
        self.assertIn("candidate.compatible_models", javascript)
        self.assertIn("Compatible models (", javascript)
        for sort_key in ("rank", "model", "performance_index", "integrity_overall", "combined_score", "tokens_per_second", "ttft_ms", "average_total_seconds", "peak_vram_mb", "speedup_vs_cpu", "status"):
            self.assertIn(f'data-sort-key="{sort_key}"', html)
        self.assertIn("buildAllRows", javascript)
        self.assertIn("sortRows", javascript)
        self.assertIn('aria-label="Backend performance comparison"', html)
        self.assertIn('aria-label="Performance history trend"', html)
        self.assertIn("Holistic capability ranks strict integrity/comprehension tiers first", html)
        self.assertLess(html.index("benchmark_leaderboard.js"), html.index("app.js"))
        self.assertNotIn("chart.js", html.lower())
        self.assertNotIn("plotly", html.lower())
        for contract in (
            "let leaderboardHistoryCache = []",
            "let integrityHistoryCache = []",
            "let leaderboardCandidateCache = []",
            "function renderBenchmarkLeaderboard",
            "function selectLeaderboardSession",
            'section === "leaderboard"',
            'setAttribute("tabindex", "0")',
            "selectedLocalperfEvaluationId = row.evaluation_id",
            'selectHardwareSection("benchmarks")',
            "renderLeaderboardDetails",
            "renderLeaderboardScatter",
            "renderLeaderboardTrend",
            "`${row.name} ${metricLabel} over time`",
            'createKpi("Lowest duration"',
            'createKpi("Best CPU-relative speed"',
            'createKpi("Probe verification"',
            'circle.addEventListener("keydown"',
            "row.availability_reason",
            "JSONCodrLeaderboard.chooseSession",
            "historyBackends",
            "Conformance:",
            "renderLeaderboardMetricComparison",
            "Benchmark model ${row.model} is not available",
            "Benchmark suite ${row.suite} is not available",
            'row.conforming === true ? "valid" : row.conforming === false ? "invalid" : "unknown"',
            "configuration_hash",
            "workload hash ${row.workload_hash || \"unavailable\"}",
            "JSONCodrLeaderboard.joinIntegrity",
        ):
            self.assertIn(contract, javascript)
        self.assertIn("Weighted quality + performance", html)

    def test_integrity_and_comprehension_benchmark_controls_and_runtime_contract(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        for identifier in (
            "integrity-benchmark-suite", "integrity-benchmark-model", "integrity-benchmark-run",
            "integrity-benchmark-status", "integrity-benchmark-scores",
            "integrity-benchmark-results", "integrity-benchmark-history",
        ):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn("Integrity &amp; Comprehension", html)
        self.assertIn("3 repetitions", html)
        self.assertIn("7 repetitions", html)
        self.assertIn('fetch("/api/integrity-benchmarks"', javascript)
        self.assertIn("runIntegrityBenchmark", javascript)
        self.assertIn("renderIntegrityBenchmark", javascript)
        self.assertIn("scores.integrity", javascript)
        self.assertIn("scores.comprehension", javascript)
        self.assertIn("scenario.evidence", javascript)
        self.assertIn("benchmark.suite_version", javascript)
        self.assertIn("evidence.evaluation_reason", javascript)
        for identifier in (
            "leaderboardSearch", "leaderboardModelFilter", "leaderboardBackendFilter",
            "leaderboardSuiteFilter", "leaderboardMetric",
        ):
            self.assertIn(f"elements.{identifier}.addEventListener", javascript)

    def test_gpu_telemetry_and_per_model_profile_controls_are_present(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/app.js").text

        for identifier in (
            "hardware-telemetry", "hardware-profile-model", "hardware-profile-mode",
            "hardware-profile-advanced", "hardware-profile-num-gpu", "hardware-profile-main-gpu",
            "hardware-profile-num-ctx", "hardware-profile-num-batch", "hardware-profile-save",
            "hardware-profile-reset", "hardware-profile-status",
        ):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn('fetch("/api/hardware/telemetry"', javascript)
        self.assertIn("gpu_optimization", javascript)
        self.assertIn('mode === "advanced"', javascript)
        self.assertIn("Automatic · Ollama managed", html)
        self.assertIn("GPU preferred", html)
        self.assertIn("VRAM conservative", html)

    def test_settings_saves_are_partial_and_serialized(self):
        javascript = self.client.get("/static/app.js").text
        html = self.client.get("/").text
        self.assertIn("let settingsSaveQueue = Promise.resolve()", javascript)
        self.assertIn("settingsSaveQueue.then", javascript)
        self.assertNotIn("buildUiSettings", javascript)
        self.assertIn('ui: { theme: nextThemeMode }', javascript)
        self.assertIn('primary_destination: destination', javascript)
        self.assertIn('hardware_section: section', javascript)
        self.assertIn('sidebar_collapsed: collapsed', javascript)
        self.assertIn('sidebar_width: width', javascript)
        self.assertIn("let persistedThemeMode = null", javascript)
        self.assertIn("persistedThemeMode = normalizeThemeMode(settingsState.ui.theme)", javascript)
        self.assertIn("uiCustomizationController.seedLegacyMode(persistedThemeMode)", javascript)
        self.assertIn("themeRevisionAtStart === themeSaveRevision", javascript)
        self.assertIn("skillsRevisionAtStart === skillsChangeRevision", javascript)
        self.assertIn("navigationRevisionAtStart === navigationChangeRevision", javascript)
        self.assertIn("loadApplication().then(() => queueSettingsLoad())", javascript)
        self.assertIn('id="ui-mode" class="setting-select" aria-describedby="ui-mode-help"', html)
        self.assertIn('id="setting-skills-open" type="checkbox" disabled', html)


    def test_theme_settings_and_runtime_hooks_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertIn("ui-mode", parser.ids)
        self.assertIn("ui-preset", parser.ids)

        javascript = self.client.get("/static/app.js").text
        catalog = self.client.get("/static/ui_catalog.js").text
        bootstrap = self.client.get("/static/ui_bootstrap.js").text
        controller = self.client.get("/static/ui_customization.js").text
        self.assertIn('LEGACY_THEME_KEY = "json_codr_theme"', catalog)
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', bootstrap)
        self.assertIn("seedLegacyMode", controller)
        self.assertIn("applyAppearanceState", javascript)
        self.assertIn("persistedThemeMode", javascript)

        css = self.client.get("/static/app.css").text
        self.assertIn(':root[data-theme="light"]', css)
        for variable in (
            "--focus-outline",
            "--surface-input",
            "--surface-panel",
            "--terminal-bg",
            "--error-text",
        ):
            self.assertIn(variable, css)

    def test_skillset_recommendation_and_confirmed_action_ui_contracts(self):
        html = self.client.get("/").text
        parser = IdCollector()
        parser.feed(html)
        self.assertTrue({
            "skillset-library",
            "skillset-list",
            "auto-attach-skills",
            "skill-recommendations",
            "attached-skills",
            "action-review",
            "action-list",
            "destructive-confirmation-dialog",
            "destructive-confirmation-command",
            "destructive-confirmation-cwd",
            "destructive-confirmation-risk",
            "destructive-confirmation-phrase",
            "destructive-confirmation-input",
            "destructive-confirmation-submit",
        }.issubset(parser.ids))
        self.assertIn("<details", html)

        javascript = self.client.get("/static/app.js").text
        self.assertIn('fetch("/api/skillsets")', javascript)
        self.assertIn("/skill-recommendations", javascript)
        self.assertIn("/skill-routing", javascript)
        self.assertIn("excluded_skill_ids", javascript)
        self.assertIn("recommendation.reasons", javascript)
        self.assertIn('button.textContent = "Dismiss"', javascript)
        self.assertIn('copy.textContent = "Copy"', javascript)
        self.assertIn('reject.textContent = "Reject"', javascript)
        self.assertIn('approve.textContent = "Approve and run"', javascript)
        self.assertIn("destructive-confirmation-phrase", html)
        self.assertIn("Confirmation code", html)
        self.assertIn(".trim().toUpperCase()", javascript)
        self.assertIn("if (terminalConnectionPromise) return terminalConnectionPromise", javascript)
        self.assertIn('type: "approved_action", proposal_id: proposal.id, token', javascript)
        self.assertIn('message.type === "action_started"', javascript)
        self.assertIn('message.type === "action_completed"', javascript)
        self.assertIn('message.success ? "Installation complete" : "Installation finished with errors"', javascript)
        self.assertIn('"Command accepted — installation running..."', javascript)
        self.assertIn('approve.disabled = true', javascript)
        self.assertIn("Terminal disconnected before action was accepted", javascript)
        server_source = Path("web_app/app.py").read_text(encoding="utf-8")
        self.assertIn('{"type": "action_started", "proposal_id": proposal_id}', server_source)
        self.assertIn('"type": "action_completed"', server_source)
        self.assertNotIn("runTerminalCommand(proposal.command)", javascript)
        self.assertIn("textContent", javascript)

        css = self.client.get("/static/app.css").text
        self.assertIn(".attached-skill-chip", css)
        self.assertIn(".action-card", css)
        self.assertIn(":root[data-theme=\"light\"]", css)


    def test_workspace_responsive_and_accessibility_contracts_are_present(self):
        html = self.client.get("/").text
        script = self.client.get("/static/app.js").text
        css = self.client.get("/static/app.css").text
        self.assertIn('data-workspace-mode', script)
        self.assertIn('Alt+1', script)
        self.assertIn('Alt+2', script)
        self.assertIn('Alt+3', script)
        self.assertIn('aria-valuetext', script)
        self.assertIn('workspace-announcer', html)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('[data-workspace-mode="mobile"]', css)
        self.assertIn('[data-workspace-mode="intermediate"]', css)


if __name__ == "__main__":
    unittest.main()
