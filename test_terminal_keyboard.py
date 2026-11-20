import json
import subprocess
import unittest
from pathlib import Path


MODULE = Path(__file__).parent / "web" / "terminal_keyboard.js"


class TerminalKeyboardTests(unittest.TestCase):
    def run_node(self, source):
        return subprocess.run(
            ["node", "-e", source, str(MODULE)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_clipboard_and_interrupt_chord(self):
        source = r'''
const assert = require("assert");
const createTerminalKeyboardController = require(process.argv[1]);

let time = 1000;
const copied = [];
const pasted = [];
let interrupts = 0;
const controller = createTerminalKeyboardController({
  copyText: (text) => copied.push(text),
  pasteText: () => pasted.push("requested"),
  interrupt: () => { interrupts += 1; },
  now: () => time,
  chordTimeoutMs: 1500,
});
const key = (value, extra = {}) => ({ type: "keydown", key: value, ctrlKey: true, altKey: false, metaKey: false, ...extra });

assert.strictEqual(controller.handleKeyEvent(key("c"), "selected output"), false);
assert.deepStrictEqual(copied, ["selected output"]);
assert.strictEqual(interrupts, 0);

assert.strictEqual(controller.handleKeyEvent(key("c"), ""), false);
assert.strictEqual(interrupts, 0);

assert.strictEqual(controller.handleKeyEvent(key("v"), ""), true);
assert.deepStrictEqual(pasted, []);

assert.strictEqual(controller.handleKeyEvent(key("x"), ""), false);
time += 100;
assert.strictEqual(controller.handleKeyEvent(key("c"), ""), false);
assert.strictEqual(interrupts, 1);

assert.strictEqual(controller.handleKeyEvent(key("x"), ""), false);
time += 1501;
assert.strictEqual(controller.handleKeyEvent(key("c"), ""), false);
assert.strictEqual(interrupts, 1);

assert.strictEqual(controller.handleKeyEvent(key("x"), ""), false);
assert.strictEqual(controller.handleKeyEvent({ type: "keydown", key: "a", ctrlKey: false, altKey: false, metaKey: false }, ""), true);
assert.strictEqual(controller.handleKeyEvent(key("c"), ""), false);
assert.strictEqual(interrupts, 1);

assert.strictEqual(controller.handleKeyEvent({ type: "keyup", key: "c", ctrlKey: true }, ""), true);
process.stdout.write(JSON.stringify({ copied, pasted, interrupts }));
'''
        result = self.run_node(source)
        self.assertEqual(
            json.loads(result.stdout),
            {"copied": ["selected output"], "pasted": [], "interrupts": 1},
        )

    def test_command_history_navigation_and_clear(self):
        source = r'''
const assert = require("assert");
const createTerminalKeyboardController = require(process.argv[1]);

const saved = [];
const controller = createTerminalKeyboardController({
  loadHistory: () => ["git status", "python -m unittest"],
  saveHistory: (history) => saved.push([...history]),
});

assert.strictEqual(controller.navigateHistory(-1, "draft command"), "python -m unittest");
assert.strictEqual(controller.navigateHistory(-1, "ignored"), "git status");
assert.strictEqual(controller.navigateHistory(1, "ignored"), "python -m unittest");
assert.strictEqual(controller.navigateHistory(1, "ignored"), "draft command");

controller.recordCommand("git diff");
assert.deepStrictEqual(saved.at(-1), ["git status", "python -m unittest", "git diff"]);
controller.clearCommandHistory();
assert.deepStrictEqual(saved.at(-1), []);
process.stdout.write(JSON.stringify({ saved }));
'''
        result = self.run_node(source)
        self.assertEqual(json.loads(result.stdout)["saved"][-1], [])


if __name__ == "__main__":
    unittest.main()
