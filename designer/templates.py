from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

from web_app.designer.contracts import DesignDocument, DesignNode, DesignPage, LayoutSpec


TEMPLATE_IDS = ("blank", "landing-page", "dashboard", "form")

NOC_LIGHT_TOKENS = {
    "color_background": "#f6f8fa",
    "color_surface": "#ffffff",
    "color_text": "#172033",
    "color_muted": "#667085",
    "color_accent": "#ff5f32",
    "color_border": "#d0d5dd",
    "font_family": "system-ui",
    "font_mono": "ui-monospace",
    "radius": 8,
    "spacing": 8,
    "density": "compact",
}


def _node(node_id: str, component_type: str, parent_id: str | None = None, children: Iterable[str] = (), **properties) -> DesignNode:
    return DesignNode(
        node_id=node_id,
        component_type=component_type,
        parent_id=parent_id,
        children=tuple(children),
        properties=properties,
    )


def _blank() -> tuple[DesignNode, ...]:
    return (_node("root", "container"),)


def _landing() -> tuple[DesignNode, ...]:
    return (
        _node("root", "stack", children=("hero", "features", "cta")),
        _node("hero", "stack", "root", ("title", "intro", "primary-action")),
        _node("title", "heading", "hero", text="Build a clear interface", level=1),
        _node("intro", "text", "hero", text="A portable starting point built with registered components."),
        _node("primary-action", "button", "hero", label="Get started"),
        DesignNode(node_id="features", component_type="grid", parent_id="root", children=("feature-one", "feature-two"), layout=LayoutSpec(kind="grid", columns=2)),
        _node("feature-one", "card", "features", ("feature-one-text",)),
        _node("feature-one-text", "text", "feature-one", text="Responsive structure"),
        _node("feature-two", "card", "features", ("feature-two-text",)),
        _node("feature-two-text", "text", "feature-two", text="Editable design tokens"),
        _node("cta", "link", "root", label="Learn more", href="#learn-more"),
    )


def _dashboard() -> tuple[DesignNode, ...]:
    return (
        _node("root", "grid", children=("navigation", "main")),
        _node("navigation", "navigation", "root", ("home-link",)),
        _node("home-link", "link", "navigation", label="Overview", href="#overview"),
        _node("main", "stack", "root", ("title", "metrics", "activity")),
        _node("title", "heading", "main", text="Operations dashboard", level=1),
        DesignNode(node_id="metrics", component_type="grid", parent_id="main", children=("metric-one", "metric-two"), layout=LayoutSpec(kind="grid", columns=2)),
        _node("metric-one", "card", "metrics", ("metric-one-text",)),
        _node("metric-one-text", "text", "metric-one", text="Healthy services: 12"),
        _node("metric-two", "card", "metrics", ("metric-two-text",)),
        _node("metric-two-text", "text", "metric-two", text="Open alerts: 2"),
        _node("activity", "table", "main", label="Recent activity", columns=["Event", "Status"], rows=[]),
    )


def _form() -> tuple[DesignNode, ...]:
    return (
        _node("root", "stack", children=("title", "contact-form")),
        _node("title", "heading", "root", text="Contact form", level=1),
        _node("contact-form", "form", "root", ("name", "topic", "message", "updates", "submit"), label="Contact"),
        _node("name", "input", "contact-form", label="Name", input_type="text"),
        _node("topic", "select", "contact-form", label="Topic", options=["Support", "Sales", "Other"]),
        _node("message", "textarea", "contact-form", label="Message"),
        _node("updates", "checkbox", "contact-form", label="Send me updates"),
        _node("submit", "button", "contact-form", label="Submit"),
    )


_FACTORIES = {"blank": _blank, "landing-page": _landing, "dashboard": _dashboard, "form": _form}


def create_template(template_id: str, name: str) -> DesignDocument:
    try:
        nodes = _FACTORIES[template_id]()
    except KeyError:
        raise KeyError(template_id) from None
    return DesignDocument(
        project_id=f"design-{uuid4().hex}",
        name=name,
        pages=(DesignPage(page_id="home", slug="home", root_node_id="root", title=name),),
        nodes=nodes,
        tokens=NOC_LIGHT_TOKENS,
        metadata={"template_id": template_id, "theme": "noc-light"},
    )
