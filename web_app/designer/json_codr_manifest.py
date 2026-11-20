from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from web_app.designer.contracts import DesignDocument, DesignNode, DesignPage
from web_app.designer.templates import NOC_LIGHT_TOKENS


JSON_CODR_MANIFEST_VERSION = 1
PROTECTED_REGION_IDS = (
    "application-shell", "primary-navigation", "top-bar", "workspace", "context-files-panel",
    "skills-panel", "hardware-panel", "settings-panel", "composer", "response-cards",
    "plan-review-panels", "status-indicators", "terminal-container", "designer-exit",
    "recovery-controls", "approval-controls",
)

_FULL_LOCK = ("delete", "rebind", "move_outside_region", "hide", "rename")
_COMPONENT_TYPES = {
    "application-shell": "container",
    "primary-navigation": "navigation",
    "top-bar": "container",
    "workspace": "container",
    "context-files-panel": "card",
    "skills-panel": "card",
    "hardware-panel": "card",
    "settings-panel": "card",
    "composer": "form",
    "response-cards": "list",
    "plan-review-panels": "card",
    "status-indicators": "list",
    "terminal-container": "container",
    "designer-exit": "button",
    "recovery-controls": "container",
    "approval-controls": "container",
}
_ESSENTIAL = {
    "application-shell", "primary-navigation", "settings-panel", "designer-exit",
    "recovery-controls", "approval-controls",
}


def create_json_codr_overlay(appearance_state: Mapping[str, Any] | None = None) -> DesignDocument:
    children = PROTECTED_REGION_IDS[1:]
    nodes: list[DesignNode] = []
    for node_id in PROTECTED_REGION_IDS:
        locks = _FULL_LOCK if node_id in _ESSENTIAL else ("rebind", "move_outside_region")
        if node_id == "terminal-container":
            locks = ("rebind", "move_outside_region", "delete")
        nodes.append(DesignNode(
            node_id=node_id,
            component_type=_COMPONENT_TYPES[node_id],
            parent_id=None if node_id == "application-shell" else "application-shell",
            children=children if node_id == "application-shell" else (),
            properties={"label": node_id.replace("-", " ").title()},
            locked_capabilities=locks,
        ))
    appearance = dict(appearance_state or {})
    tokens = {**NOC_LIGHT_TOKENS, **appearance}
    return DesignDocument(
        project_id="json-codr-overlay",
        name="JSON_CODR appearance",
        mode="json_codr",
        pages=(DesignPage(page_id="application", slug="application", root_node_id="application-shell"),),
        nodes=tuple(nodes),
        tokens=tokens,
        metadata={"manifest_version": JSON_CODR_MANIFEST_VERSION, "theme": appearance.get("preset", "noc-light")},
    )
