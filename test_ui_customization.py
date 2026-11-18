import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
CATALOG_MODULE = ROOT / "web" / "ui_catalog.js"
CONTROLLER_MODULE = ROOT / "web" / "ui_customization.js"


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


if __name__ == "__main__":
    unittest.main()
