import json
import subprocess
import unittest
from pathlib import Path


MODULE = Path(__file__).parent / "web" / "workspace_layout.js"


class WorkspaceLayoutTests(unittest.TestCase):
    def run_node(self, source):
        return subprocess.run(
            ["node", "-e", source, str(MODULE)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_defaults_move_focus_and_close_preserve_one_panel_identity(self):
        source = r'''
const assert = require("assert");
const createWorkspaceLayoutController = require(process.argv[1]);
const saved = [];
const controller = createWorkspaceLayoutController({
  availablePanels: ["files", "activity", "terminal", "skills"],
  panelPlacements: {
    files: ["left", "right", "bottom"],
    activity: ["right", "bottom"],
    terminal: ["bottom", "left", "right"],
    skills: ["right", "bottom"],
  },
  save: (state) => saved.push(state),
});

assert.deepStrictEqual(controller.getState().regions, {
  left: ["files"], right: ["activity"], bottom: ["terminal"],
});
controller.open("skills", "right");
controller.open("skills", "right");
assert.deepStrictEqual(controller.getState().regions.right, ["activity", "skills"]);
assert.strictEqual(controller.getState().focusedPanel, "skills");
controller.move("skills", "bottom");
assert.deepStrictEqual(controller.getState().regions.right, ["activity"]);
assert.deepStrictEqual(controller.getState().regions.bottom, ["terminal", "skills"]);
controller.focus("terminal");
assert.strictEqual(controller.getState().focusedPanel, "terminal");
controller.close("terminal");
assert.deepStrictEqual(controller.getState().regions.bottom, ["skills"]);
assert.strictEqual(controller.getState().focusedPanel, "skills");
assert.ok(saved.length >= 4);
process.stdout.write(JSON.stringify(controller.getState()));
'''
        result = self.run_node(source)
        self.assertEqual(json.loads(result.stdout)["regions"]["bottom"], ["skills"])

    def test_sizes_collapse_presets_and_reset_are_bounded_and_persisted(self):
        source = r'''
const assert = require("assert");
const createWorkspaceLayoutController = require(process.argv[1]);
const controller = createWorkspaceLayoutController({
  availablePanels: ["files", "activity", "terminal", "output"],
  panelPlacements: {
    files: ["left"], activity: ["right"], terminal: ["bottom"], output: ["bottom"],
  },
  bounds: {
    left: { min: 180, max: 420, default: 260 },
    right: { min: 200, max: 480, default: 300 },
    bottom: { min: 140, max: 600, default: 260 },
  },
});
controller.resize("left", 20);
controller.resize("right", 9999);
controller.resize("bottom", "bad");
assert.deepStrictEqual(controller.getState().sizes, { left: 180, right: 480, bottom: 260 });
controller.collapse("right", true);
assert.strictEqual(controller.getState().collapsed.right, true);
controller.applyPreset("focus");
assert.deepStrictEqual(controller.getState().collapsed, { left: true, right: true, bottom: true });
controller.applyPreset("code");
assert.deepStrictEqual(controller.getState().collapsed, { left: false, right: true, bottom: false });
assert.deepStrictEqual(controller.getState().regions.left, ["files"]);
assert.deepStrictEqual(controller.getState().regions.bottom, ["terminal"]);
controller.applyPreset("observe");
assert.deepStrictEqual(controller.getState().collapsed, { left: true, right: false, bottom: false });
assert.deepStrictEqual(controller.getState().regions.right, ["activity"]);
assert.deepStrictEqual(controller.getState().regions.bottom, ["output"]);
controller.reset();
assert.strictEqual(controller.getState().preset, "default");
assert.deepStrictEqual(controller.getState().sizes, { left: 260, right: 300, bottom: 260 });
process.stdout.write(JSON.stringify(controller.getState()));
'''
        self.run_node(source)

    def test_corrupt_persistence_recovers_and_narrow_viewport_migrates_identity(self):
        source = r'''
const assert = require("assert");
const createWorkspaceLayoutController = require(process.argv[1]);
const corrupt = {
  version: 99,
  regions: { left: ["terminal", "terminal", "unknown"], right: "bad", bottom: [] },
  sizes: { left: -10, right: "wide", bottom: 9000 },
  collapsed: { left: "yes" },
  focusedPanel: "unknown",
};
const controller = createWorkspaceLayoutController({
  availablePanels: ["files", "activity", "terminal"],
  panelPlacements: {
    files: ["left", "bottom"], activity: ["right", "bottom"], terminal: ["bottom", "right"],
  },
  load: () => corrupt,
});
assert.deepStrictEqual(controller.getState().regions, {
  left: ["files"], right: ["activity"], bottom: ["terminal"],
});
controller.applyViewport(700);
const narrow = controller.getState();
assert.deepStrictEqual(narrow.regions.left, []);
assert.deepStrictEqual(narrow.regions.right, []);
assert.deepStrictEqual(narrow.regions.bottom.sort(), ["activity", "files", "terminal"]);
assert.strictEqual(new Set(narrow.regions.bottom).size, 3);
assert.strictEqual(narrow.focusedPanel, "terminal");
controller.applyViewport(1400);
assert.deepStrictEqual(controller.getState().regions, {
  left: ["files"], right: ["activity"], bottom: ["terminal"],
});
process.stdout.write(JSON.stringify(narrow));
'''
        result = self.run_node(source)
        self.assertEqual(len(json.loads(result.stdout)["regions"]["bottom"]), 3)


if __name__ == "__main__":
    unittest.main()
