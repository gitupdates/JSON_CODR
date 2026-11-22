"""Structured UI Designer contracts and services."""

from web_app.designer.contracts import DesignDocument, normalize_design
from web_app.designer.components import ComponentDefinition, ComponentRegistry
from web_app.designer.json_codr_manifest import create_json_codr_overlay
from web_app.designer.store import DesignerStore, ProjectConflict, ProjectRevision
from web_app.designer.templates import create_template
from web_app.designer.access import (
    CapabilityProfile,
    CapabilityRule,
    DesignPolicyContext,
    PolicyDecision,
    ProfileAssignment,
    resolve_design_capability,
)

__all__ = [
    "DesignDocument",
    "ComponentDefinition",
    "ComponentRegistry",
    "DesignerStore",
    "ProjectConflict",
    "ProjectRevision",
    "create_json_codr_overlay",
    "create_template",
    "normalize_design",
    "CapabilityProfile",
    "CapabilityRule",
    "DesignPolicyContext",
    "PolicyDecision",
    "ProfileAssignment",
    "resolve_design_capability",
]
