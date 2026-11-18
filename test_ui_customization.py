import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
CATALOG_MODULE = ROOT / "web" / "ui_catalog.js"
CONTROLLER_MODULE = ROOT / "web" / "ui_customization.js"
BOOTSTRAP_MODULE = ROOT / "web" / "ui_bootstrap.js"


class GammaUICustomizationTests(unittest.TestCase):
    def run_node(self, source, module=CATALOG_MODULE, extra_modules=()):
        modules = [module, *extra_modules]
        for required in modules:
            self.assertTrue(required.is_file(), f"{required.relative_to(ROOT)} must exist")
        result = subprocess.run(
            ["node", "-e", source, *map(str, modules)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_catalog_defaults_recover_corrupt_state_and_filter_overrides(self):
        source = r'''
const assert = require("assert");
const ui = require(process.argv[1]);
assert.strictEqual(ui.DEFAULT_STATE.preset, "noc-light");
assert.strictEqual(ui.normalizeState(null, "dark").preset, "noc-light");
assert.strictEqual(ui.normalizeState({schema: 99, preset: "terminal-focus"}, "system").preset, "noc-light");
const normalized = ui.normalizeState({
  schema: 1,
  preset: "noc-light",
  components: {navigation: "rail", panels: "unknown", surprise: "x"},
});
assert.deepStrictEqual(normalized.components, {navigation: "rail"});
process.stdout.write(JSON.stringify(normalized));
'''
        result = self.run_node(source)
        self.assertEqual(json.loads(result.stdout)["preset"], "noc-light")

    def test_fixed_modes_and_accessibility_combinations_normalize_safely(self):
        source = r'''
const assert = require("assert");
const ui = require(process.argv[1]);
const noc = ui.normalizeState({schema: 1, preset: "noc-light", mode: "dark"});
assert.strictEqual(noc.mode, "dark");
assert.strictEqual(ui.effectiveState(noc, false).effectiveMode, "light");
const classic = ui.normalizeState({schema: 1, preset: "json-codr-classic", mode: "system"});
assert.strictEqual(ui.effectiveState(classic, true).effectiveMode, "dark");
assert.strictEqual(ui.effectiveState(classic, false).effectiveMode, "light");
assert.strictEqual(ui.normalizeState({schema: 1, preset: "accessible-read", density: "compact"}).density, "comfortable");
const dyslexic = ui.normalizeState({schema: 1, preset: "gamma-operations", typography: "opendyslexic", density: "compact"});
assert.strictEqual(dyslexic.density, "comfortable");
'''
        self.run_node(source)

    def test_every_preset_has_an_allowed_variant_for_every_component(self):
        source = r'''
const assert = require("assert");
const ui = require(process.argv[1]);
for (const [presetId, preset] of Object.entries(ui.PRESETS)) {
  for (const [family, definition] of Object.entries(ui.COMPONENTS)) {
    assert.ok(Object.hasOwn(preset.components, family), `${presetId} missing ${family}`);
    assert.ok(definition.variants.includes(preset.components[family]), `${presetId} has invalid ${family}`);
  }
}
'''
        self.run_node(source)

    def test_controller_prefers_versioned_state_and_migrates_legacy_only_on_save(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const createController = require(process.argv[2]);
const writes = [];
const removed = [];
const stored = {
  [catalog.STORAGE_KEY]: {schema: 1, preset: "json-codr-classic", mode: "light", components: {}},
  [catalog.LEGACY_THEME_KEY]: "dark",
};
const controller = createController({
  catalog,
  load: key => stored[key] ?? null,
  save: (key, value) => writes.push([key, value]),
  removeLegacy: key => removed.push(key),
});
assert.strictEqual(controller.getState().preset, "json-codr-classic");
assert.strictEqual(controller.getState().mode, "light");
assert.strictEqual(writes.length, 0);
controller.save();
assert.strictEqual(writes.length, 1);
assert.strictEqual(writes[0][0], catalog.STORAGE_KEY);
assert.deepStrictEqual(removed, [catalog.LEGACY_THEME_KEY]);

const migrationWrites = [];
const migrated = createController({
  catalog,
  load: key => key === catalog.LEGACY_THEME_KEY ? "system" : null,
  save: (key, value) => migrationWrites.push([key, value]),
});
assert.strictEqual(migrated.getState().mode, "system");
assert.strictEqual(migrationWrites.length, 0);
'''
        self.run_node(source, CATALOG_MODULE, [CONTROLLER_MODULE])

    def test_server_legacy_mode_seeds_without_writing_or_breaking_fixed_preset(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const createController = require(process.argv[2]);
const writes = [];
const controller = createController({catalog, load: () => null, save: (...args) => writes.push(args)});
controller.seedLegacyMode("dark");
assert.strictEqual(controller.getState().mode, "dark");
assert.strictEqual(controller.getEffectiveState().effectiveMode, "light");
assert.strictEqual(writes.length, 0);
controller.selectPreset("json-codr-classic");
assert.strictEqual(controller.getEffectiveState().effectiveMode, "dark");
'''
        self.run_node(source, CATALOG_MODULE, [CONTROLLER_MODULE])

    def test_controller_cancel_restores_snapshot_without_writing(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const createController = require(process.argv[2]);
const writes = [];
const applied = [];
const controller = createController({
  catalog,
  load: () => null,
  save: (key, value) => writes.push([key, value]),
  apply: value => applied.push(value),
});
const before = controller.begin();
controller.selectPreset("terminal-focus");
controller.setComponent("navigation", "rail");
controller.setDensity("comfortable");
assert.strictEqual(controller.getDraft().preset, "terminal-focus");
const restored = controller.cancel();
assert.deepStrictEqual(restored, before);
assert.deepStrictEqual(controller.getDraft(), before);
assert.strictEqual(writes.length, 0);
assert.ok(applied.length >= 4);
'''
        self.run_node(source, CATALOG_MODULE, [CONTROLLER_MODULE])

    def test_controller_validates_mutations_and_persists_navigation_override(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const createController = require(process.argv[2]);
let persisted = null;
const controller = createController({
  catalog,
  load: () => null,
  save: (key, value) => persisted = value,
});
controller.begin();
controller.setComponent("navigation", "rail");
const valid = controller.getDraft();
controller.setComponent("navigation", "not-real");
controller.setComponent("surprise", "rail");
assert.deepStrictEqual(controller.getDraft(), valid);
controller.save();
assert.strictEqual(persisted.components.navigation, "rail");

const reloaded = createController({catalog, load: key => key === catalog.STORAGE_KEY ? persisted : null});
assert.strictEqual(reloaded.getState().components.navigation, "rail");
reloaded.begin();
reloaded.selectPreset("gamma-operations");
assert.strictEqual(reloaded.getDraft().mode, persisted.mode);
assert.deepStrictEqual(reloaded.getDraft().components, {});
'''
        self.run_node(source, CATALOG_MODULE, [CONTROLLER_MODULE])

    def test_first_paint_bootstrap_applies_validated_root_attributes_without_writing(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const bootstrapUI = require(process.argv[2]);
const writes = [];
const root = {dataset: {}, style: {colorScheme: ""}};
const state = {
  schema: 1, preset: "terminal-focus", mode: "light", density: "comfortable",
  typography: "system", components: {navigation: "operations"},
};
const storage = {
  getItem: key => key === catalog.STORAGE_KEY ? JSON.stringify(state) : null,
  setItem: (...args) => writes.push(args),
};
const effective = bootstrapUI({catalog, storage, root, systemDark: false});
assert.strictEqual(effective.preset, "terminal-focus");
assert.strictEqual(root.dataset.theme, "dark");
assert.strictEqual(root.style.colorScheme, "dark");
assert.strictEqual(root.dataset.uiPreset, "terminal-focus");
assert.strictEqual(root.dataset.uiDensity, "comfortable");
assert.strictEqual(root.dataset.uiTypography, "system");
assert.strictEqual(root.dataset.uiNavigation, "operations");
assert.strictEqual(root.dataset.uiPanels, "flat");
assert.strictEqual(writes.length, 0);
'''
        self.run_node(source, CATALOG_MODULE, [BOOTSTRAP_MODULE])

    def test_first_paint_bootstrap_recovers_corrupt_state_and_reads_legacy_mode(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const bootstrapUI = require(process.argv[2]);
const root = {dataset: {}, style: {}};
const storage = {getItem: key => key === catalog.STORAGE_KEY ? "{broken" : "dark"};
const effective = bootstrapUI({catalog, storage, root, systemDark: true});
assert.strictEqual(effective.preset, "noc-light");
assert.strictEqual(effective.mode, "dark");
assert.strictEqual(effective.effectiveMode, "light");
assert.strictEqual(root.dataset.theme, "light");
assert.strictEqual(root.dataset.uiNavigation, "operations");
'''
        self.run_node(source, CATALOG_MODULE, [BOOTSTRAP_MODULE])

    def test_index_loads_ui_bootstrap_before_styles_and_controller_before_application(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        catalog = '/static/ui_catalog.js?v=1.0.18-alpha.10'
        bootstrap = '/static/ui_bootstrap.js?v=1.0.18-alpha.10'
        stylesheet = '/static/app.css?v=1.0.18-alpha.10'
        controller = '/static/ui_customization.js?v=1.0.18-alpha.10'
        application = '/static/app.js?v=1.0.18-alpha.10'
        self.assertIn(catalog, html)
        self.assertIn(bootstrap, html)
        self.assertIn(controller, html)
        self.assertLess(html.index(catalog), html.index(bootstrap))
        self.assertLess(html.index(bootstrap), html.index(stylesheet))
        self.assertLess(html.index(controller), html.index(application))
        self.assertNotIn("vendor/charts", html)
        self.assertNotIn("vendor/leaflet", html)

    def test_gamma_styles_cover_every_preset_component_and_accessibility_contract(self):
        gamma_path = ROOT / "web" / "gamma.css"
        self.assertTrue(gamma_path.is_file(), "web/gamma.css must exist")
        css = gamma_path.read_text(encoding="utf-8")
        source = r'''
const catalog = require(process.argv[1]);
console.log(JSON.stringify({presets: Object.keys(catalog.PRESETS), components: catalog.COMPONENTS}));
'''
        completed = subprocess.run(
            ["node", "-e", source, str(CATALOG_MODULE)], cwd=ROOT, text=True,
            capture_output=True, check=True,
        )
        inventory = json.loads(completed.stdout)
        for preset in inventory["presets"]:
            self.assertIn(f'[data-ui-preset="{preset}"]', css)
        for family, definition in inventory["components"].items():
            attribute = f"ui-{family}"
            for variant in definition["variants"]:
                self.assertIn(f'[data-{attribute}="{variant}"]', css)
        for contract in (
            'color-scheme: light', '--signal-blue:', '--signal-orange:',
            '@media (prefers-reduced-motion: reduce)', ':focus-visible',
            '@media (max-width:', '[data-ui-navigation="high-contrast"]',
            '[data-ui-panels="flat"]', '[data-ui-tabs="segmented"]',
        ):
            self.assertIn(contract, css)

    def test_gamma_fonts_are_approved_licensed_and_loaded_after_application_css(self):
        fonts = ROOT / "web" / "fonts"
        expected = {
            "fonts.css", "opendyslexic-400.woff2", "opendyslexic-700.woff2",
            "OpenDyslexic-OFL.txt", "THIRD_PARTY_NOTICES.md",
        }
        self.assertTrue(fonts.is_dir(), "web/fonts must exist")
        actual = {path.name for path in fonts.iterdir() if path.is_file()}
        self.assertEqual(actual, expected)
        self.assertGreater((fonts / "opendyslexic-400.woff2").stat().st_size, 1000)
        self.assertGreater((fonts / "opendyslexic-700.woff2").stat().st_size, 1000)
        notice = (fonts / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("C:\\UI\\UI.zip", notice)
        self.assertIn("SHA-256", notice)
        self.assertFalse(any("ibm-plex" in name.lower() for name in actual))
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app_css = '/static/app.css?v=1.0.18-alpha.10'
        fonts_css = '/static/fonts/fonts.css?v=1.0.18-alpha.10'
        gamma_css = '/static/gamma.css?v=1.0.18-alpha.10'
        self.assertLess(html.index(app_css), html.index(fonts_css))
        self.assertLess(html.index(fonts_css), html.index(gamma_css))

    def test_gamma_has_no_ibm_plex_dependency_or_catalog_option(self):
        for relative in (
            "web/ui_catalog.js", "web/fonts/fonts.css", "web/fonts/THIRD_PARTY_NOTICES.md",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertNotIn("ibm plex", content, relative)
            self.assertNotIn("ibm-plex", content, relative)
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
assert.strictEqual(catalog.DEFAULT_STATE.typography, "system");
assert.ok(!Object.hasOwn(catalog.TYPOGRAPHIES, "ibm-plex"));
'''
        self.run_node(source)

    def test_appearance_editor_previews_catalog_values_and_controls_draft_lifecycle(self):
        source = r'''
const assert = require("assert");
const catalog = require(process.argv[1]);
const createController = require(process.argv[2]);
assert.strictEqual(typeof createController.bindUICustomizationEditor, "function");
const writes = [];
const root = {dataset: {}, style: {}};
const apply = effective => {
  root.dataset.theme = effective.effectiveMode;
  root.dataset.uiPreset = effective.preset;
  root.dataset.uiDensity = effective.density;
  root.dataset.uiTypography = effective.typography;
  for (const [family, variant] of Object.entries(effective.components)) {
    root.dataset[`ui${family[0].toUpperCase()}${family.slice(1)}`] = variant;
  }
};
const controller = createController({catalog, load: () => null, save: (key, value) => writes.push([key, value]), apply});
class Fake {
  constructor() { this.value = ""; this.disabled = false; this.textContent = ""; this.innerHTML = ""; this.listeners = {}; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  fire(type, target = this) { this.listeners[type]?.({target, preventDefault() {}}); }
}
const elements = Object.fromEntries([
  "preset", "mode", "density", "typography", "components", "summary", "status",
  "save", "cancel", "resetPreset", "restoreDefaults", "modeHelp",
].map(key => [key, new Fake()]));
const editor = createController.bindUICustomizationEditor({controller, catalog, elements});
assert.ok(elements.preset.innerHTML.includes("NOC Light"));
assert.ok(elements.components.innerHTML.includes("data-family=\"navigation\""));
elements.preset.value = "terminal-focus"; elements.preset.fire("change");
assert.strictEqual(root.dataset.theme, "dark");
assert.strictEqual(elements.mode.disabled, true);
elements.components.fire("change", {dataset: {family: "navigation"}, value: "operations"});
assert.strictEqual(root.dataset.uiNavigation, "operations");
assert.ok(elements.summary.textContent.includes("1 override"));
elements.preset.value = "gamma-operations"; elements.preset.fire("change");
elements.typography.value = "opendyslexic"; elements.typography.fire("change");
assert.strictEqual(controller.getDraft().density, "comfortable");
elements.cancel.fire("click");
assert.strictEqual(controller.getDraft().preset, "noc-light");
assert.strictEqual(writes.length, 0);
editor.begin();
elements.preset.value = "gamma-operations"; elements.preset.fire("change");
elements.save.fire("click");
assert.strictEqual(writes.length, 1);
elements.restoreDefaults.fire("click");
assert.deepStrictEqual(controller.getDraft(), catalog.DEFAULT_STATE);
'''
        self.run_node(source, CATALOG_MODULE, [CONTROLLER_MODULE])

    def test_appearance_editor_markup_is_accessible_and_complete(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for element_id in (
            "ui-preset", "ui-mode", "ui-density", "ui-typography", "ui-component-overrides",
            "ui-override-summary", "ui-preview-status", "ui-save", "ui-cancel",
            "ui-reset-preset", "ui-restore-defaults",
        ):
            self.assertIn(f'id="{element_id}"', html)
        for control_id in ("ui-preset", "ui-mode", "ui-density", "ui-typography"):
            self.assertIn(f'for="{control_id}"', html)
        self.assertIn('id="ui-preview-status" class="meta" role="status" aria-live="polite"', html)
        self.assertNotIn('id="setting-theme"', html)


if __name__ == "__main__":
    unittest.main()
