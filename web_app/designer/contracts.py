from __future__ import annotations

import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer, field_validator, model_validator

from web_app.core.canonical import canonical_digest as compute_canonical_digest


Identifier = str
Digest = str
Breakpoint = Literal["desktop", "tablet", "mobile"]
LayoutKind = Literal["stack", "grid", "freeform"]
ActionKind = Literal[
    "navigate", "open_dialog", "close_dialog", "switch_tab", "toggle_visibility",
    "set_value", "reset_form", "submit_https_form", "request_connector",
]
LockedCapability = Literal["delete", "rebind", "move_outside_region", "hide", "rename"]

MAX_NODES = 1000
MAX_DEPTH = 32
KNOWN_COMPONENTS = frozenset({
    "container", "stack", "grid", "text", "heading", "button", "link", "input",
    "textarea", "select", "checkbox", "image", "icon", "navigation", "tabs", "card",
    "table", "list", "form", "dialog", "divider", "spacer", "component_instance",
})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FORBIDDEN_KEY = re.compile(
    r"(^on[a-z]|script|handler|secret|credential|token|cookie|(^|_)(file_)?path($|_))",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


class DesignerContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class FrozenMap(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("design mappings are immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenMap({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(child) for child in value]
    return value


def _identifier(value: str, label: str = "identifier") -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _safe_json(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            text = str(key)
            if _FORBIDDEN_KEY.search(text):
                raise ValueError(f"forbidden design key: {'.'.join(path + (text,))}")
            _safe_json(child, path=path + (text,))
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _safe_json(child, path=path + (str(index),))
        return
    if isinstance(value, str) and _WINDOWS_ABSOLUTE.match(value):
        raise ValueError("absolute machine paths are not allowed in a design")


class LayoutSpec(DesignerContract):
    kind: LayoutKind = "stack"
    x: float | None = Field(default=None, ge=0, le=10000)
    y: float | None = Field(default=None, ge=0, le=10000)
    width: float | None = Field(default=None, gt=0, le=10000)
    height: float | None = Field(default=None, gt=0, le=10000)
    gap: float | None = Field(default=None, ge=0, le=512)
    columns: int | None = Field(default=None, ge=1, le=24)

    @model_validator(mode="after")
    def validate_layout_fields(self) -> "LayoutSpec":
        positioned = (self.x, self.y, self.width, self.height)
        if self.kind != "freeform" and any(value is not None for value in positioned):
            raise ValueError("coordinates and dimensions are limited to freeform layouts")
        if self.kind == "freeform" and any(value is None for value in positioned):
            raise ValueError("freeform layouts require x, y, width, and height")
        if self.kind != "grid" and self.columns is not None:
            raise ValueError("columns are limited to grid layouts")
        return self


class BreakpointOverride(DesignerContract):
    properties: Mapping[str, JsonValue] = Field(default_factory=dict)
    styles: Mapping[str, JsonValue] = Field(default_factory=dict)
    layout: LayoutSpec | None = None

    @field_validator("properties", "styles")
    @classmethod
    def validate_safe_values(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _safe_json(value)
        return _freeze(value)

    @field_serializer("properties", "styles")
    def serialize_values(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw(value)


class ActionBinding(DesignerContract):
    kind: ActionKind
    event: str = Field(default="activate", pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    arguments: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _safe_json(value)
        return _freeze(value)

    @field_serializer("arguments")
    def serialize_arguments(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw(value)


class ReferenceRecord(DesignerContract):
    reference_id: Identifier
    kind: Literal["screenshot", "extract", "archive", "playwright"]
    content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_label: str = Field(min_length=1, max_length=256)
    license_note: str = Field(default="", max_length=512)

    @field_validator("reference_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value, "reference identifier")

    @field_validator("source_label")
    @classmethod
    def reject_source_paths(cls, value: str) -> str:
        if _WINDOWS_ABSOLUTE.match(value) or value.startswith(("/", "\\\\")):
            raise ValueError("reference labels cannot contain source paths")
        return value


class DesignNode(DesignerContract):
    node_id: Identifier
    component_type: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    parent_id: Identifier | None = None
    children: tuple[Identifier, ...] = ()
    properties: Mapping[str, JsonValue] = Field(default_factory=dict)
    styles: Mapping[str, JsonValue] = Field(default_factory=dict)
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    breakpoint_overrides: Mapping[Breakpoint, BreakpointOverride] = Field(default_factory=dict)
    actions: tuple[ActionBinding, ...] = ()
    locked_capabilities: tuple[LockedCapability, ...] = ()
    inert_placeholder: bool = False

    @field_validator("node_id", "parent_id")
    @classmethod
    def validate_ids(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, "node identifier")

    @field_validator("children")
    @classmethod
    def validate_children(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for child in value:
            _identifier(child, "child identifier")
        if len(value) != len(set(value)):
            raise ValueError("child identifiers must be unique")
        return value

    @field_validator("properties", "styles")
    @classmethod
    def validate_safe_values(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _safe_json(value)
        return _freeze(value)

    @field_validator("breakpoint_overrides")
    @classmethod
    def freeze_breakpoint_overrides(
        cls, value: Mapping[Breakpoint, BreakpointOverride],
    ) -> Mapping[Breakpoint, BreakpointOverride]:
        return FrozenMap(value)

    @field_serializer("properties", "styles")
    def serialize_values(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw(value)

    @field_serializer("breakpoint_overrides")
    def serialize_breakpoint_overrides(
        self, value: Mapping[Breakpoint, BreakpointOverride],
    ) -> dict[str, dict[str, JsonValue]]:
        return {key: child.model_dump(mode="json") for key, child in value.items()}

    @model_validator(mode="after")
    def derive_inert_state(self) -> "DesignNode":
        if self.component_type not in KNOWN_COMPONENTS:
            object.__setattr__(self, "inert_placeholder", True)
        return self


class DesignPage(DesignerContract):
    page_id: Identifier
    slug: str = Field(min_length=1, max_length=128)
    root_node_id: Identifier
    title: str = Field(default="", max_length=256)

    @field_validator("page_id", "root_node_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _identifier(value, "page node identifier")

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not _SLUG.fullmatch(value):
            raise ValueError("page slug must be route safe")
        return value


class DesignDocument(DesignerContract):
    schema_version: Literal[2] = 2
    project_id: Identifier
    name: str = Field(min_length=1, max_length=256)
    mode: Literal["project", "json_codr"] = "project"
    pages: tuple[DesignPage, ...] = Field(min_length=1, max_length=100)
    nodes: tuple[DesignNode, ...] = Field(min_length=1, max_length=MAX_NODES)
    tokens: Mapping[str, JsonValue] = Field(default_factory=dict)
    references: tuple[ReferenceRecord, ...] = ()
    metadata: Mapping[str, JsonValue] = Field(default_factory=dict)
    canonical_digest: Digest | None = None

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        return _identifier(value, "project identifier")

    @field_validator("tokens", "metadata")
    @classmethod
    def validate_safe_values(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _safe_json(value)
        return _freeze(value)

    @field_serializer("tokens", "metadata")
    def serialize_values(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw(value)

    @model_validator(mode="after")
    def validate_graph_and_digest(self) -> "DesignDocument":
        page_ids = [page.page_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("page identifiers must be unique")
        slugs = [page.slug for page in self.pages]
        if len(slugs) != len(set(slugs)):
            raise ValueError("page slugs must be unique")
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node identifiers must be unique")
        if len(self.nodes) > MAX_NODES:
            raise ValueError(f"a design may contain at most {MAX_NODES} nodes")
        by_id = {node.node_id: node for node in self.nodes}
        for page in self.pages:
            if page.root_node_id not in by_id:
                raise ValueError(f"page {page.page_id} has a missing root node")
        for current in self.nodes:
            if current.parent_id is not None:
                parent = by_id.get(current.parent_id)
                if parent is None or current.node_id not in parent.children:
                    raise ValueError(f"node {current.node_id} has an inconsistent parent relationship")
            for child_id in current.children:
                child = by_id.get(child_id)
                if child is None:
                    raise ValueError(f"node {current.node_id} has a missing child")
                if child.parent_id != current.node_id:
                    raise ValueError(f"node {child_id} has an inconsistent parent relationship")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str, depth: int) -> None:
            if node_id in visiting:
                raise ValueError("design node cycle detected")
            if depth > MAX_DEPTH:
                raise ValueError(f"design depth exceeds {MAX_DEPTH}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for child_id in by_id[node_id].children:
                visit(child_id, depth + 1)
            visiting.remove(node_id)
            visited.add(node_id)

        for current in self.nodes:
            visit(current.node_id, 1)
        expected = compute_canonical_digest(self.model_dump(mode="json", exclude={"canonical_digest"}))
        if self.canonical_digest is not None and self.canonical_digest != expected:
            raise ValueError("design canonical digest does not match its content")
        object.__setattr__(self, "canonical_digest", expected)
        return self

    def effective_node(self, node_id: str, breakpoint: Breakpoint) -> dict[str, Any]:
        current = next((item for item in self.nodes if item.node_id == node_id), None)
        if current is None:
            raise KeyError(node_id)
        result = current.model_dump(mode="json")
        result.pop("breakpoint_overrides", None)
        order = ("desktop", "tablet", "mobile")
        for name in order[: order.index(breakpoint) + 1]:
            override = current.breakpoint_overrides.get(name)
            if override is None:
                continue
            result["properties"] = {**result["properties"], **dict(override.properties)}
            result["styles"] = {**result["styles"], **dict(override.styles)}
            if override.layout is not None:
                result["layout"] = override.layout.model_dump(mode="json")
        return result


def normalize_design(candidate: object) -> DesignDocument:
    if isinstance(candidate, DesignDocument):
        return candidate
    if not isinstance(candidate, Mapping):
        raise ValueError("design input must be an object")
    if candidate.get("schema_version") == 2:
        return DesignDocument.model_validate(candidate)
    if candidate.get("schema") == 1 and "preset" in candidate:
        tokens = {
            key: candidate[key]
            for key in ("preset", "mode", "density", "typography", "components")
            if key in candidate
        }
        return DesignDocument(
            project_id="json-codr-overlay",
            name="JSON_CODR appearance",
            mode="json_codr",
            pages=(DesignPage(page_id="application", slug="application", root_node_id="shell"),),
            nodes=(DesignNode(
                node_id="shell",
                component_type="container",
                locked_capabilities=("delete", "rebind", "move_outside_region"),
            ),),
            tokens=tokens,
            metadata={"migrated_from": "appearance-v1"},
        )
    return DesignDocument.model_validate(candidate)
