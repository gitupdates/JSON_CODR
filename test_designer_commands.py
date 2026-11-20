import json
import subprocess
import unittest
from pathlib import Path

from web_app.designer.components import ComponentRegistry
from web_app.designer.contracts import (
    DesignDocument,
    DesignNode,
    DesignPage,
    LayoutSpec,
)


ROOT = Path(__file__).parent
MODEL = ROOT / "web" / "designer_model.js"
COMMANDS = ROOT / "web" / "designer_commands.js"


def make_document(*, locked=False):
    root = DesignNode(
        node_id="root",
        component_type="container",
        children=("a", "b", "c", "d"),
        layout=LayoutSpec(kind="freeform", x=0, y=0, width=640, height=480),
    )
    nodes = [root]
    for node_id, x, y in (("a", 16, 16), ("b", 80, 16), ("c", 144, 16), ("d", 208, 16)):
        nodes.append(DesignNode(
            node_id=node_id,
            component_type="button" if node_id == "a" else "image" if node_id == "d" else "text",
            parent_id="root",
            properties={"label": node_id} if node_id == "a" else {"asset_id": "asset-1"} if node_id == "d" else {"text": node_id},
            layout=LayoutSpec(kind="freeform", x=x, y=y, width=48, height=32),
            locked_capabilities=("delete", "rebind", "hide", "rename") if locked and node_id == "a" else (),
        ))
    return DesignDocument(
        project_id="project-1",
        name="Command tests",
        pages=(DesignPage(page_id="page-1", slug="home", root_node_id="root"),),
        nodes=tuple(nodes),
    ).model_dump(mode="json")


def registry_json():
    registry = ComponentRegistry.builtins()
    return {
        component_type: registry.get(component_type).model_dump(mode="json")
        for component_type in registry.types()
    }


class DesignerCommandTests(unittest.TestCase):
    def run_node(self, source, *, locked=False):
        result = subprocess.run(
            [
                "node", "-e", source, str(MODEL), str(COMMANDS),
                json.dumps(make_document(locked=locked)),
                json.dumps(registry_json()),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            self.fail(result.stderr)
        return result

    def test_every_serializable_command_has_a_working_inverse(self):
        source = r'''
const assert = require("assert");
const createDesignerModel = require(process.argv[2]);
const original = JSON.parse(process.argv[3]);
const registry = JSON.parse(process.argv[4]);
const commands = [
  { type: "insert", node: { node_id: "new", component_type: "text", properties: { text: "new" }, layout: { kind: "freeform", x: 208, y: 16, width: 48, height: 32 } }, parentId: "root" },
  { type: "remove", nodeId: "a" },
  { type: "move", nodeId: "a", parentId: "root", index: 1, layout: { kind: "freeform", x: 24, y: 40, width: 48, height: 32 } },
  { type: "resize", nodeId: "a", layout: { kind: "freeform", x: 16, y: 16, width: 64, height: 40 } },
  { type: "group", nodeIds: ["a", "b"], groupId: "group-1", componentType: "stack", index: 0 },
  { type: "duplicate", nodeId: "a", nodeMap: { a: "a-copy" } },
  { type: "reorder", nodeId: "c", index: 0 },
  { type: "set-property", nodeId: "a", key: "label", value: "Updated" },
  { type: "set-style", nodeId: "a", key: "color", value: "#123456" },
  { type: "set-action", nodeId: "a", index: 0, action: { kind: "navigate", event: "activate", arguments: { page: "home" } } },
  { type: "set-breakpoint", nodeId: "a", breakpoint: "mobile", override: { styles: { font_size: "18px" } } },
  { type: "replace-asset", nodeId: "d", assetId: "asset-2" },
];
for (const command of commands) {
  const model = createDesignerModel(original, registry);
  const before = model.getDocument();
  const result = model.dispatch({ ...command, projectId: before.project_id, expectedDigest: before.canonical_digest });
  assert.strictEqual(result.ok, true, `${command.type}: ${JSON.stringify(result.conflict)}`);
  if (command.type === "move") {
    const moved = result.document.nodes.find((item) => item.node_id === "a");
    assert.deepStrictEqual([moved.layout.x, moved.layout.y], [24, 40]);
  }
  assert.ok(result.inverse, `${command.type} omitted inverse`);
  const reverted = model.dispatch(result.inverse);
  assert.strictEqual(reverted.ok, true, `${command.type} inverse failed`);
  assert.deepStrictEqual(reverted.document, before, `${command.type} inverse did not restore document`);
}
const grouped = createDesignerModel(original, registry);
const groupResult = grouped.dispatch({
  type: "group", projectId: original.project_id, expectedDigest: original.canonical_digest,
  nodeIds: ["a", "b"], groupId: "group-1", componentType: "stack",
});
assert.strictEqual(groupResult.ok, true);
const ungrouped = grouped.dispatch({
  type: "ungroup", projectId: original.project_id,
  expectedDigest: groupResult.document.canonical_digest, nodeId: "group-1",
});
assert.strictEqual(ungrouped.ok, true);
assert.deepStrictEqual(ungrouped.document, original);
const regrouped = grouped.dispatch(ungrouped.inverse);
assert.strictEqual(regrouped.ok, true);
assert.deepStrictEqual(regrouped.document, groupResult.document);
const model = createDesignerModel(original, registry);
const digest = model.getDocument().canonical_digest;
const inserted = model.dispatch({
  type: "insert", projectId: "project-1", expectedDigest: digest,
  parentId: "root",
  node: { node_id: "new", component_type: "text", properties: {}, layout: { kind: "freeform", x: 200, y: 16, width: 40, height: 32 } },
});
assert.strictEqual(model.undo().ok, true);
assert.deepStrictEqual(model.getDocument(), original);
assert.strictEqual(model.redo().ok, true);
assert.deepStrictEqual(model.getDocument(), inserted.document);
process.stdout.write(JSON.stringify(model.getDocument()));
'''
        result = self.run_node(source)
        document = DesignDocument.model_validate(json.loads(result.stdout))
        self.assertEqual(document.nodes[-1].node_id, "new")

    def test_selection_alignment_distribution_keyboard_move_and_snapping(self):
        source = r'''
const assert = require("assert");
const createDesignerModel = require(process.argv[2]);
const model = createDesignerModel(JSON.parse(process.argv[3]), JSON.parse(process.argv[4]), { snap: true, gridSize: 8 });
const send = (command) => model.dispatch({
  ...command, projectId: model.getDocument().project_id,
  expectedDigest: model.getDocument().canonical_digest,
});
const reversible = (command) => {
  const before = model.getDocument();
  const result = send(command);
  assert.strictEqual(result.ok, true);
  const reverted = model.dispatch(result.inverse);
  assert.strictEqual(reverted.ok, true);
  assert.deepStrictEqual(reverted.document, before);
  return result;
};
model.select(["a", "b", "c"]);
assert.deepStrictEqual(model.selection(), ["a", "b", "c"]);
reversible({ type: "align", nodeIds: ["a", "b", "c"], axis: "y", edge: "start" });
reversible({ type: "distribute", nodeIds: ["a", "b", "c"], axis: "x" });
const beforeNudge = model.getDocument();
const nudged = send({ type: "nudge", nodeId: "a", dx: 5, dy: 5 });
assert.strictEqual(nudged.ok, true);
assert.deepStrictEqual(model.getDocument().nodes.find((item) => item.node_id === "a").layout, {
  kind: "freeform", x: 24, y: 24, width: 48, height: 32, gap: null, columns: null,
});
assert.strictEqual(model.dispatch(nudged.inverse).ok, true);
assert.deepStrictEqual(model.getDocument(), beforeNudge);
process.stdout.write(JSON.stringify(model.getDocument()));
'''
        result = self.run_node(source)
        DesignDocument.model_validate(json.loads(result.stdout))

    def test_conflicts_protection_and_bounded_freeform_coordinates(self):
        source = r'''
const assert = require("assert");
const createDesignerModel = require(process.argv[2]);
const doc = JSON.parse(process.argv[3]);
const registry = JSON.parse(process.argv[4]);
const model = createDesignerModel(doc, registry);
const dispatch = (command, projectId = doc.project_id, expectedDigest = model.getDocument().canonical_digest) =>
  model.dispatch({ ...command, projectId, expectedDigest });
assert.strictEqual(dispatch({ type: "remove", nodeId: "a" }, "other-project").conflict.code, "wrong-project");
assert.strictEqual(dispatch({ type: "remove", nodeId: "a" }, doc.project_id, "sha256:stale").conflict.code, "stale-document");
assert.strictEqual(dispatch({ type: "remove", nodeId: "missing" }).conflict.code, "missing-node");
assert.strictEqual(dispatch({ type: "move", nodeId: "root", parentId: "a" }).conflict.code, "protected-node");
assert.strictEqual(dispatch({ type: "set-property", nodeId: "b", key: "label", value: "invalid" }).conflict.code, "invalid-property");
assert.strictEqual(dispatch({ type: "set-action", nodeId: "b", index: 0, action: { kind: "navigate", event: "activate", arguments: {} } }).conflict.code, "invalid-action");
assert.strictEqual(dispatch({
  type: "insert", parentId: "b",
  node: { node_id: "bad-child", component_type: "text" },
}).conflict.code, "invalid-parent");
const before = model.getDocument();
assert.strictEqual(dispatch({ type: "resize", nodeId: "a", layout: { kind: "freeform", x: 620, y: 0, width: 48, height: 32 } }).conflict.code, "out-of-bounds");
assert.deepStrictEqual(model.getDocument(), before);
process.stdout.write(JSON.stringify(model.getDocument()));
'''
        self.assertTrue(self.run_node(source).stdout)

        locked_source = r'''
const assert = require("assert");
const createDesignerModel = require(process.argv[2]);
const model = createDesignerModel(JSON.parse(process.argv[3]), JSON.parse(process.argv[4]));
const send = (command) => model.dispatch({
  ...command, projectId: "project-1",
  expectedDigest: model.getDocument().canonical_digest,
});
assert.strictEqual(send({ type: "remove", nodeId: "a" }).conflict.code, "protected-node");
assert.strictEqual(send({ type: "set-action", nodeId: "a", index: 0, action: { kind: "navigate", event: "activate", arguments: {} } }).conflict.code, "protected-node");
assert.strictEqual(send({ type: "set-property", nodeId: "a", key: "label", value: "Changed" }).conflict.code, "protected-node");
assert.strictEqual(send({ type: "set-style", nodeId: "a", key: "color", value: "#123456" }).ok, true);
assert.strictEqual(send({ type: "set-style", nodeId: "a", key: "display", value: "none" }).conflict.code, "protected-node");
process.stdout.write("ok");
'''
        self.assertEqual(self.run_node(locked_source, locked=True).stdout, "ok")

    def test_breakpoint_inheritance_undo_limit_and_redo_invalidation(self):
        source = r'''
const assert = require("assert");
const createDesignerModel = require(process.argv[2]);
const model = createDesignerModel(JSON.parse(process.argv[3]), JSON.parse(process.argv[4]), { historyLimit: 2 });
const send = (command) => model.dispatch({
  ...command, projectId: "project-1",
  expectedDigest: model.getDocument().canonical_digest,
});
assert.strictEqual(send({ type: "set-breakpoint", nodeId: "a", breakpoint: "tablet", override: { styles: { color: "red" } } }).ok, true);
assert.strictEqual(send({ type: "set-breakpoint", nodeId: "a", breakpoint: "mobile", override: { properties: { label: "mobile" } } }).ok, true);
assert.strictEqual(model.effectiveNode("a", "mobile").styles.color, "red");
assert.strictEqual(model.effectiveNode("a", "mobile").properties.label, "mobile");
assert.strictEqual(model.effectiveNode("a", "mobile").layout.x, 16);
assert.strictEqual(send({ type: "set-property", nodeId: "b", key: "text", value: "one" }).ok, true);
assert.strictEqual(model.undo().ok, true);
assert.strictEqual(model.undo().ok, true);
assert.strictEqual(model.undo().conflict.code, "history-limit");
assert.strictEqual(send({ type: "set-property", nodeId: "c", key: "text", value: "branch" }).ok, true);
assert.strictEqual(model.redo().conflict.code, "nothing-to-redo");
process.stdout.write(JSON.stringify(model.getDocument()));
'''
        result = self.run_node(source)
        DesignDocument.model_validate(json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
