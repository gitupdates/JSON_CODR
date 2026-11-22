import unittest

from web_app.designer.access import (
    CapabilityProfile,
    CapabilityRule,
    DesignPolicyContext,
    ProfileAssignment,
    resolve_design_capability,
)


class DesignerAccessTests(unittest.TestCase):
    def test_explicit_resource_deny_overrides_role_and_profile_grants(self):
        profile = CapabilityProfile(
            profile_id="profile-layout-author",
            label="Layout author",
            grants=("design.layout.write",),
        )
        context = DesignPolicyContext(
            subject_id="account-alice",
            role="administrator",
            profiles=(profile,),
            assignments=(
                ProfileAssignment(
                    assignment_id="assignment-alice-layout",
                    subject_id="account-alice",
                    profile_id=profile.profile_id,
                    resource="project:alpha",
                ),
            ),
            resource_rules=(
                CapabilityRule(
                    resource="project:alpha/page:home",
                    action="design.layout.write",
                    effect="deny",
                ),
            ),
        )

        decision = resolve_design_capability(
            context,
            "project:alpha/page:home",
            "design.layout.write",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.source, "resource-deny")

    def test_owner_retains_recovery_authority(self):
        context = DesignPolicyContext(
            subject_id="account-owner",
            role="owner",
            resource_rules=(
                CapabilityRule(resource="system:recovery", action="design.recovery.manage", effect="deny"),
            ),
        )

        decision = resolve_design_capability(context, "system:recovery", "design.recovery.manage")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "owner-recovery-invariant")

    def test_administrator_defaults_include_unrestricted_design_actions(self):
        context = DesignPolicyContext(subject_id="account-admin", role="administrator")

        for action in (
            "design.tokens.write",
            "design.layout.write",
            "design.components.import",
            "design.html.write",
            "design.css.write",
            "design.script.write",
            "design.publish",
            "design.permissions.manage",
        ):
            with self.subTest(action=action):
                self.assertTrue(
                    resolve_design_capability(context, "project:alpha", action).allowed,
                    action,
                )

    def test_script_authority_is_distinct_from_visual_design_authority(self):
        context = DesignPolicyContext(subject_id="account-designer", role="designer")

        self.assertTrue(
            resolve_design_capability(context, "project:alpha", "design.layout.write").allowed,
        )
        script = resolve_design_capability(context, "project:alpha", "design.script.write")
        unknown = resolve_design_capability(context, "project:alpha", "design.unknown.write")

        self.assertFalse(script.allowed)
        self.assertEqual(script.source, "default-deny")
        self.assertFalse(unknown.allowed)
        self.assertEqual(unknown.reason, "unknown action")


if __name__ == "__main__":
    unittest.main()
