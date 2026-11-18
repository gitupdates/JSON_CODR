import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
CATALOG_MODULE = ROOT / "web" / "ui_catalog.js"


class GammaUICustomizationTests(unittest.TestCase):
    def run_node(self, source, module=CATALOG_MODULE):
        self.assertTrue(module.is_file(), f"{module.relative_to(ROOT)} must exist")
        return subprocess.run(
            ["node", "-e", source, str(module)],
            check=True,
            capture_output=True,
            text=True,
        )

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


if __name__ == "__main__":
    unittest.main()
