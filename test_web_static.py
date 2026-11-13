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
        self.assertIn("V1.0.3", response.text)
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

    def test_attachment_context_tray_controls_are_present(self):
        response = self.client.get("/")
        parser = IdCollector()
        parser.feed(response.text)
        self.assertTrue(
            {
                "context-toggle",
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
                "terminal-toggle",
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
                "skills-toggle",
                "settings-toggle",
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


    def test_settings_toggle_brings_panel_into_view(self):
        javascript = self.client.get("/static/app.js").text
        self.assertIn("elements.settingsPanel.scrollIntoView", javascript)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', javascript)
        self.assertIn("elements.settingTheme.focus", javascript)

    def test_settings_saves_are_partial_and_serialized(self):
        javascript = self.client.get("/static/app.js").text
        html = self.client.get("/").text
        self.assertIn("let settingsSaveQueue = Promise.resolve()", javascript)
        self.assertIn("settingsSaveQueue.then", javascript)
        self.assertNotIn("buildUiSettings", javascript)
        self.assertIn('ui: { theme: nextThemeMode }', javascript)
        self.assertIn('ui: { skill_catalog_open: open }', javascript)
        self.assertIn("let persistedThemeMode = null", javascript)
        self.assertIn("persistedThemeMode = normalizeThemeMode(settingsState.ui.theme)", javascript)
        self.assertIn("applyThemeMode(persistedThemeMode", javascript)
        self.assertIn("themeRevisionAtStart === themeSaveRevision", javascript)
        self.assertIn("skillsRevisionAtStart === skillsChangeRevision", javascript)
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


if __name__ == "__main__":
    unittest.main()
