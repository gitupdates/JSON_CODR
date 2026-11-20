from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


BUILTIN_COMPONENT_TYPES = (
    "container", "stack", "grid", "text", "heading", "button", "link", "input",
    "textarea", "select", "checkbox", "image", "icon", "navigation", "tabs", "card",
    "table", "list", "form", "dialog", "divider", "spacer", "component_instance",
)

CONTAINER_CHILDREN = BUILTIN_COMPONENT_TYPES


class ComponentDefinition(BaseModel):
    """Serializable component capabilities; never contains renderer functions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_type: str
    label: str
    allowed_children: tuple[str, ...] = ()
    property_schema: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default_properties: dict[str, Any] = Field(default_factory=dict)
    default_styles: dict[str, Any] = Field(default_factory=dict)
    semantic_exporter: str
    action_slots: tuple[str, ...] = ()
    data_slots: tuple[str, ...] = ()
    accessibility_requirements: tuple[str, ...] = ()
    json_codr_capabilities: tuple[str, ...] = ("style", "typography")
    project_capabilities: tuple[str, ...] = (
        "insert", "remove", "move", "resize", "style", "typography", "actions",
    )
    inert_placeholder: bool = False


def _definition(
    component_type: str,
    *,
    label: str | None = None,
    children: tuple[str, ...] = (),
    tag: str | None = None,
    properties: Mapping[str, dict[str, Any]] | None = None,
    actions: tuple[str, ...] = (),
    accessibility: tuple[str, ...] = (),
    defaults: Mapping[str, Any] | None = None,
) -> ComponentDefinition:
    return ComponentDefinition(
        component_type=component_type,
        label=label or component_type.replace("_", " ").title(),
        allowed_children=children,
        property_schema=dict(properties or {}),
        default_properties=dict(defaults or {}),
        semantic_exporter=tag or component_type,
        action_slots=actions,
        accessibility_requirements=accessibility,
    )


def _builtins() -> tuple[ComponentDefinition, ...]:
    text = {"text": {"type": "string", "maxLength": 10000}}
    label = {"label": {"type": "string", "maxLength": 256}}
    return (
        _definition("container", children=CONTAINER_CHILDREN, tag="div"),
        _definition("stack", children=CONTAINER_CHILDREN, tag="div"),
        _definition("grid", children=CONTAINER_CHILDREN, tag="div"),
        _definition("text", tag="p", properties=text, defaults={"text": "Text"}),
        _definition("heading", tag="heading", properties={**text, "level": {"type": "integer", "minimum": 1, "maximum": 6}}, defaults={"text": "Heading", "level": 2}),
        _definition("button", tag="button", properties=label, defaults={"label": "Button"}, actions=("activate",), accessibility=("label",)),
        _definition("link", tag="a", properties={**label, "href": {"type": "string"}}, actions=("activate",), accessibility=("label",)),
        _definition("input", tag="input", properties={**label, "input_type": {"enum": ["text", "email", "number", "password", "search", "tel", "url"]}}, accessibility=("label",)),
        _definition("textarea", tag="textarea", properties=label, accessibility=("label",)),
        _definition("select", tag="select", properties={**label, "options": {"type": "array"}}, actions=("change",), accessibility=("label",)),
        _definition("checkbox", tag="input", properties=label, actions=("change",), accessibility=("label",)),
        _definition("image", tag="img", properties={"asset_id": {"type": "string"}, "alt": {"type": "string"}}, accessibility=("alt",)),
        _definition("icon", tag="span", properties={"name": {"type": "string"}, "label": {"type": "string"}}, accessibility=("label",)),
        _definition("navigation", tag="nav", children=("link", "button", "list", "component_instance"), accessibility=("label",)),
        _definition("tabs", tag="div", children=("button", "container", "component_instance"), actions=("change",), accessibility=("label",)),
        _definition("card", tag="article", children=CONTAINER_CHILDREN),
        _definition("table", tag="table", properties={"columns": {"type": "array"}, "rows": {"type": "array"}}, accessibility=("label",)),
        _definition("list", tag="ul", children=("text", "link", "card", "component_instance")),
        _definition("form", tag="form", children=CONTAINER_CHILDREN, actions=("submit",), accessibility=("label",)),
        _definition("dialog", tag="dialog", children=CONTAINER_CHILDREN, actions=("open", "close"), accessibility=("label",)),
        _definition("divider", tag="hr"),
        _definition("spacer", tag="div", properties={"size": {"type": "number", "minimum": 0, "maximum": 512}}),
        _definition("component_instance", tag="div", properties={"definition_id": {"type": "string"}}),
    )


class ComponentRegistry:
    def __init__(self, definitions: Iterable[ComponentDefinition] = ()) -> None:
        self._definitions: dict[str, ComponentDefinition] = {}
        for definition in definitions:
            self.register(definition)

    @classmethod
    def builtins(cls) -> "ComponentRegistry":
        return cls(_builtins())

    def register(self, definition: ComponentDefinition) -> None:
        if definition.component_type in self._definitions:
            raise ValueError(f"component already registered: {definition.component_type}")
        self._definitions[definition.component_type] = definition

    def get(self, component_type: str) -> ComponentDefinition:
        try:
            return self._definitions[component_type]
        except KeyError:
            raise KeyError(component_type) from None

    def resolve(self, component_type: str) -> ComponentDefinition:
        definition = self._definitions.get(component_type)
        if definition is not None:
            return definition
        return ComponentDefinition(
            component_type=component_type,
            label=f"Unsupported: {component_type}",
            semantic_exporter="inert-placeholder",
            inert_placeholder=True,
            json_codr_capabilities=(),
            project_capabilities=(),
        )

    def types(self) -> tuple[str, ...]:
        return tuple(self._definitions)
