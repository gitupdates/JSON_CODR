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


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])


class WebStaticTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(FakeService()))

    def test_root_serves_the_complete_chat_interface(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("V1.0.12", response.text)
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
            }.issubset(parser.ids)
        )

    def test_static_assets_are_served_with_correct_types(self):
        css = self.client.get("/static/app.css")
        javascript = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertIn("text/css", css.headers["content-type"])
        self.assertEqual(javascript.status_code, 200)
        self.assertIn("javascript", javascript.headers["content-type"])

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
        for destination in ("chat", "terminal", "context", "skills", "hardware", "settings"):
            self.assertIn(f'data-destination="{destination}"', html)
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
        ):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn('data-hardware-view="benchmarks"', html)
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
        self.assertIn('/api/hardware/model-compatibility', javascript)
        self.assertIn('/api/inference/models/search', javascript)
        self.assertIn('model.status === "accelerated"', javascript)

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
        self.assertIn("applyThemeMode(persistedThemeMode", javascript)
        self.assertIn("themeRevisionAtStart === themeSaveRevision", javascript)
        self.assertIn("skillsRevisionAtStart === skillsChangeRevision", javascript)
        self.assertIn("navigationRevisionAtStart === navigationChangeRevision", javascript)
        self.assertIn("queueSettingsLoad().catch", javascript)
        self.assertIn('id="setting-theme" class="setting-select" aria-describedby="setting-theme-help" disabled', html)
        self.assertIn('id="setting-skills-open" type="checkbox" disabled', html)


    def test_theme_settings_and_runtime_hooks_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertIn("setting-theme", parser.ids)
        self.assertIn("json_codr_theme", response.text)

        javascript = self.client.get("/static/app.js").text
        self.assertIn("const VALID_THEME_MODES", javascript)
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', javascript)
        self.assertIn('addEventListener("change"', javascript)
        self.assertIn("applyThemeMode", javascript)
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


if __name__ == "__main__":
    unittest.main()
