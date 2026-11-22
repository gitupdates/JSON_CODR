from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from web_app.designer.contracts import DesignerContract


DesignRole = Literal[
    "owner",
    "administrator",
    "designer",
    "editor",
    "contributor",
    "reviewer",
    "viewer",
]
RuleEffect = Literal["allow", "deny"]

DESIGN_ACTIONS = frozenset(
    {
        "design.tokens.write",
        "design.layout.write",
        "design.components.import",
        "design.html.write",
        "design.css.write",
        "design.script.write",
        "design.publish",
        "design.permissions.manage",
        "design.recovery.manage",
        "design.preview.read",
        "design.review.write",
    }
)

_ROLE_GRANTS: dict[DesignRole, frozenset[str]] = {
    "owner": DESIGN_ACTIONS,
    "administrator": DESIGN_ACTIONS,
    "designer": frozenset(
        {
            "design.tokens.write",
            "design.layout.write",
            "design.components.import",
            "design.html.write",
            "design.css.write",
            "design.preview.read",
            "design.review.write",
        }
    ),
    "editor": frozenset(
        {
            "design.tokens.write",
            "design.layout.write",
            "design.preview.read",
            "design.review.write",
        }
    ),
    "contributor": frozenset({"design.layout.write", "design.preview.read", "design.review.write"}),
    "reviewer": frozenset({"design.preview.read", "design.review.write"}),
    "viewer": frozenset({"design.preview.read"}),
}


class CapabilityRule(DesignerContract):
    resource: str = Field(min_length=1, max_length=512)
    action: str = Field(min_length=1, max_length=128)
    effect: RuleEffect

    @field_validator("action")
    @classmethod
    def known_action(cls, value: str) -> str:
        if value not in DESIGN_ACTIONS:
            raise ValueError("unknown design action")
        return value


class CapabilityProfile(DesignerContract):
    profile_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    label: str = Field(min_length=1, max_length=200)
    grants: tuple[str, ...] = ()
    denies: tuple[str, ...] = ()

    @field_validator("grants", "denies")
    @classmethod
    def known_actions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(value not in DESIGN_ACTIONS for value in values):
            raise ValueError("unknown design action")
        return tuple(dict.fromkeys(values))


class ProfileAssignment(DesignerContract):
    assignment_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    subject_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=128)
    resource: str = Field(min_length=1, max_length=512)


class DesignPolicyContext(DesignerContract):
    subject_id: str = Field(min_length=1, max_length=128)
    role: DesignRole
    profiles: tuple[CapabilityProfile, ...] = ()
    assignments: tuple[ProfileAssignment, ...] = ()
    resource_rules: tuple[CapabilityRule, ...] = ()


class PolicyDecision(DesignerContract):
    allowed: bool
    source: str
    reason: str


def _covers(scope: str, resource: str) -> bool:
    return scope == "*" or resource == scope or resource.startswith(f"{scope}/")


def resolve_design_capability(
    context: DesignPolicyContext,
    resource: str,
    action: str,
) -> PolicyDecision:
    if context.role == "owner" and action == "design.recovery.manage":
        return PolicyDecision(allowed=True, source="owner-recovery-invariant", reason="fixed owner authority")
    if action not in DESIGN_ACTIONS:
        return PolicyDecision(allowed=False, source="default-deny", reason="unknown action")

    applicable_rules = tuple(rule for rule in context.resource_rules if rule.action == action and _covers(rule.resource, resource))
    if any(rule.effect == "deny" for rule in applicable_rules):
        return PolicyDecision(allowed=False, source="resource-deny", reason="explicit resource denial")
    if any(rule.effect == "allow" for rule in applicable_rules):
        return PolicyDecision(allowed=True, source="resource-grant", reason="explicit resource grant")

    profiles = {profile.profile_id: profile for profile in context.profiles}
    applicable_profiles = tuple(
        profiles[assignment.profile_id]
        for assignment in context.assignments
        if assignment.subject_id == context.subject_id
        and assignment.profile_id in profiles
        and _covers(assignment.resource, resource)
    )
    if any(action in profile.denies for profile in applicable_profiles):
        return PolicyDecision(allowed=False, source="profile-deny", reason="assigned profile denial")
    if any(action in profile.grants for profile in applicable_profiles):
        return PolicyDecision(allowed=True, source="profile-grant", reason="assigned profile grant")
    if action in _ROLE_GRANTS[context.role]:
        return PolicyDecision(allowed=True, source="role-default", reason=f"{context.role} default")
    return PolicyDecision(allowed=False, source="default-deny", reason="not granted")
