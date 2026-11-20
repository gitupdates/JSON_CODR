import copy
import unittest

from pydantic import ValidationError

from web_app.designer.contracts import (
    ActionBinding,
    BreakpointOverride,
    DesignDocument,
    DesignNode,
    DesignPage,
    LayoutSpec,
    ReferenceRecord,
    normalize_design,
)


def node(node_id: str, *, parent_id: str | None = None, children: tuple[str, ...] = (), **changes):
    values = {
        "node_id": node_id,
        "component_type": "container" if children else "text",
        "parent_id": parent_id,
        "children": children,
        "properties": {"text": node_id},
    }
    values.update(changes)
    return DesignNode(**values)


def document(*nodes: DesignNode, pages: tuple[DesignPage, ...] | None = None, **changes):
    values = {
        "project_id": "project-1",
        "name": "Operations console",
        "pages": pages or (DesignPage(page_id="page-home", slug="home", root_node_id="root"),),
        "nodes": nodes or (node("root", children=("title",)), node("title", parent_id="root")),
    }
    values.update(changes)
    return DesignDocument(**values)


class DesignerContractTests(unittest.TestCase):
    def test_digest_is_stable_and_rejects_a_claim_for_different_content(self):
        first = document()
        second = DesignDocument.model_validate(first.model_dump(mode="json"))

        self.assertEqual(first.canonical_digest, second.canonical_digest)
        changed = first.model_dump(mode="json")
        changed["name"] = "Changed"
        changed["canonical_digest"] = first.canonical_digest
        with self.assertRaisesRegex(ValidationError, "canonical digest"):
            DesignDocument.model_validate(changed)

    def test_nested_contract_mappings_are_immutable_after_digesting(self):
        result = document(tokens={"color": {"primary": "#123456"}})

        with self.assertRaises(TypeError):
            result.tokens["color"] = {"primary": "#ffffff"}
        with self.assertRaises(TypeError):
            result.tokens["color"]["primary"] = "#ffffff"
        with self.assertRaises(TypeError):
            result.nodes[0].properties["text"] = "changed"

    def test_pages_and_nodes_require_unique_identifiers_and_slugs(self):
        with self.assertRaisesRegex(ValidationError, "page identifiers"):
            document(pages=(
                DesignPage(page_id="same", slug="home", root_node_id="root"),
                DesignPage(page_id="same", slug="other", root_node_id="root"),
            ))
        with self.assertRaisesRegex(ValidationError, "page slugs"):
            document(pages=(
                DesignPage(page_id="one", slug="home", root_node_id="root"),
                DesignPage(page_id="two", slug="home", root_node_id="root"),
            ))
        with self.assertRaisesRegex(ValidationError, "node identifiers"):
            document(node("root"), node("root"))
        with self.assertRaises(ValidationError):
            DesignPage(page_id="bad", slug="../escape", root_node_id="root")

    def test_parent_child_relationships_and_page_roots_must_be_consistent(self):
        with self.assertRaisesRegex(ValidationError, "missing root"):
            document(node("root"), pages=(DesignPage(page_id="home", slug="home", root_node_id="missing"),))
        with self.assertRaisesRegex(ValidationError, "parent relationship"):
            document(node("root", children=("child",)), node("child", parent_id=None))
        with self.assertRaisesRegex(ValidationError, "missing child"):
            document(node("root", children=("missing",)))
        with self.assertRaisesRegex(ValidationError, "cycle"):
            document(node("root", parent_id="child", children=("child",)), node("child", parent_id="root", children=("root",)))

    def test_document_bounds_node_count_and_depth(self):
        many = tuple(node(f"n-{index}") for index in range(1001))
        with self.assertRaisesRegex(ValidationError, "at most 1000"):
            document(*many)

        chain = []
        for index in range(34):
            parent = None if index == 0 else f"n-{index - 1}"
            children = () if index == 33 else (f"n-{index + 1}",)
            chain.append(node(f"n-{index}", parent_id=parent, children=children))
        with self.assertRaisesRegex(ValidationError, "depth"):
            document(*chain, pages=(DesignPage(page_id="home", slug="home", root_node_id="n-0"),))

    def test_freeform_coordinates_are_bounded_and_forbidden_on_flow_layouts(self):
        with self.assertRaisesRegex(ValidationError, "freeform"):
            LayoutSpec(kind="stack", x=12, y=20)
        with self.assertRaises(ValidationError):
            LayoutSpec(kind="freeform", x=-1, y=0, width=100, height=100)
        valid = LayoutSpec(kind="freeform", x=12, y=20, width=320, height=180)
        self.assertEqual((valid.x, valid.y, valid.width, valid.height), (12, 20, 320, 180))

    def test_breakpoint_overrides_inherit_without_materializing_redundant_values(self):
        root = node("root", children=("title",), layout=LayoutSpec(kind="stack", gap=16))
        title = node("title", parent_id="root", breakpoint_overrides={
            "tablet": BreakpointOverride(styles={"font_size": "24px"}),
        })
        result = document(root, title).effective_node("title", "mobile")

        self.assertEqual(result["styles"], {"font_size": "24px"})
        stored = document(root, title).model_dump(mode="json")["nodes"][1]["breakpoint_overrides"]
        self.assertEqual(set(stored), {"tablet"})

    def test_actions_accept_only_the_declarative_catalog(self):
        for kind in ("navigate", "open_dialog", "close_dialog", "switch_tab", "toggle_visibility", "set_value", "reset_form", "submit_https_form", "request_connector"):
            self.assertEqual(ActionBinding(kind=kind, arguments={}).kind, kind)
        with self.assertRaises(ValidationError):
            ActionBinding(kind="run_javascript", arguments={"code": "alert(1)"})

    def test_unknown_components_are_preserved_as_inert_placeholders(self):
        result = document(node("root", component_type="vendor.future-widget"))

        self.assertEqual(result.nodes[0].component_type, "vendor.future-widget")
        self.assertTrue(result.nodes[0].inert_placeholder)

    def test_locked_capabilities_are_known_and_cannot_conflict(self):
        locked = node("root", locked_capabilities=("delete", "rebind", "move_outside_region"))
        self.assertEqual(locked.locked_capabilities, ("delete", "rebind", "move_outside_region"))
        with self.assertRaises(ValidationError):
            node("root", locked_capabilities=("execute_script",))

    def test_forbidden_executable_secret_and_absolute_path_keys_are_rejected_recursively(self):
        for payload in (
            {"onclick": "alert(1)"},
            {"nested": {"api_token": "hidden"}},
            {"asset_path": "C:\\private\\logo.png"},
            {"cookie": "session=secret"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    node("root", properties=payload)

    def test_references_require_content_digests_and_never_store_source_paths(self):
        reference = ReferenceRecord(
            reference_id="ref-1",
            kind="screenshot",
            content_digest="sha256:" + "a" * 64,
            source_label="Authorized dashboard",
        )
        self.assertEqual(reference.source_label, "Authorized dashboard")
        with self.assertRaises(ValidationError):
            ReferenceRecord(
                reference_id="ref-2", kind="archive", content_digest="sha256:" + "b" * 64,
                source_label="C:\\private\\ui.zip",
            )

    def test_normalize_design_explicitly_converts_legacy_appearance_without_mutating_it(self):
        legacy = {
            "schema": 1,
            "preset": "noc-light",
            "mode": "light",
            "density": "compact",
            "typography": "system",
            "components": {"navigation": "operations"},
        }
        original = copy.deepcopy(legacy)

        migrated = normalize_design(legacy)

        self.assertEqual(legacy, original)
        self.assertEqual(migrated.schema_version, 2)
        self.assertEqual(migrated.mode, "json_codr")
        self.assertEqual(migrated.metadata["migrated_from"], "appearance-v1")
        self.assertEqual(migrated.tokens["preset"], "noc-light")


if __name__ == "__main__":
    unittest.main()
