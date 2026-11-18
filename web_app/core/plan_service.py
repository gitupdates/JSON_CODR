from __future__ import annotations

from collections.abc import Mapping

from web_app.core.capabilities import CapabilityRegistry
from web_app.core.contracts import (
    EffectClass,
    PlanReviewDecision,
    PlanReviewStatus,
    PlanRevision,
    PlannedStep,
    RevisionAuthor,
    StepReviewStatus,
)
from web_app.core.store import ConcurrencyConflict, TaskStore


class PlanConflict(RuntimeError):
    def __init__(self, message: str, current: PlanRevision) -> None:
        super().__init__(message)
        self.current_revision = current.revision
        self.current_digest = current.canonical_digest


_EDITABLE_STEP_FIELDS = {
    "title", "purpose", "dependencies", "capability_id", "operation", "target_path",
    "arguments", "expected_evidence", "origins", "connector",
}

_EFFECTS = {
    "read": EffectClass.observe,
    "search": EffectClass.observe,
    "session": EffectClass.observe,
    "bounded_edit": EffectClass.bounded_edit,
    "write": EffectClass.bounded_edit,
    "edit": EffectClass.bounded_edit,
    "test": EffectClass.test,
    "command": EffectClass.command,
    "execute": EffectClass.command,
    "network": EffectClass.network,
    "install": EffectClass.install,
    "commit": EffectClass.git_local,
    "push": EffectClass.publish,
    "destructive": EffectClass.destructive,
}


class PlanService:
    """Single append-only writer for plan revisions and review decisions."""

    def __init__(self, store: TaskStore, registry: CapabilityRegistry) -> None:
        self.store = store
        self.registry = registry

    def create(self, task_id: str, plan: PlanRevision) -> PlanRevision:
        self._validate_steps(plan.steps)
        prepared = self._copy_plan(plan, review_status=PlanReviewStatus.in_review)
        return self.store.append_plan(task_id, prepared)

    def approve_plan(
        self, task_id: str, plan_id: str, revision: int, principal: str, expected_digest: str,
    ) -> PlanReviewDecision:
        return self._decision(task_id, plan_id, revision, principal, expected_digest, "approve")

    def reject_plan(
        self, task_id: str, plan_id: str, revision: int, principal: str,
        expected_digest: str, reason: str,
    ) -> PlanReviewDecision:
        return self._decision(
            task_id, plan_id, revision, principal, expected_digest, "reject", reason=reason,
        )

    def approve_step(
        self, task_id: str, plan_id: str, revision: int, step_id: str,
        principal: str, expected_digest: str,
    ) -> PlanReviewDecision:
        return self._decision(
            task_id, plan_id, revision, principal, expected_digest, "approve", step_id=step_id,
        )

    def reject_step(
        self, task_id: str, plan_id: str, revision: int, step_id: str,
        principal: str, expected_digest: str, reason: str,
    ) -> PlanReviewDecision:
        return self._decision(
            task_id, plan_id, revision, principal, expected_digest, "reject",
            step_id=step_id, reason=reason,
        )

    def edit_step(
        self, task_id: str, plan_id: str, revision: int, step_id: str,
        principal: str, expected_digest: str, changes: Mapping[str, object],
    ) -> PlanRevision:
        current = self._exact_current(task_id, plan_id, revision, expected_digest)
        if "calls" in changes:
            raise ValueError("a plan step represents exactly one capability call")
        unsupported = set(changes) - _EDITABLE_STEP_FIELDS
        if unsupported:
            raise ValueError(f"field is not editable: {sorted(unsupported)[0]}")
        old_steps = {step.step_id: step for step in current.steps}
        if step_id not in old_steps:
            raise KeyError(step_id)

        changed = old_steps[step_id]
        payload = changed.model_dump(mode="python", exclude={"canonical_digest"})
        payload.update(changes)
        payload["plan_revision"] = revision + 1
        payload["effect_class"] = self._effect(str(payload["operation"]), payload.get("connector"))
        payload["review_status"] = StepReviewStatus.pending
        replacement = PlannedStep.model_validate(payload)

        invalidated = self._dependents(current.steps, step_id) | {step_id}
        prior_statuses = self._review_statuses(task_id, plan_id, revision)
        next_steps = []
        for old in current.steps:
            if old.step_id == step_id:
                next_steps.append(replacement)
                continue
            status = StepReviewStatus.pending if old.step_id in invalidated else prior_statuses.get(
                old.step_id, old.review_status,
            )
            next_steps.append(self._copy_step(old, revision + 1, review_status=status))
        return self._append_revision(
            task_id, current, principal, expected_digest, tuple(next_steps),
            summary=current.summary, reason=f"Edited step {step_id}",
        )

    def revise_plan(
        self, task_id: str, plan_id: str, revision: int, principal: str,
        expected_digest: str, *, summary: str, reason: str,
    ) -> PlanRevision:
        current = self._exact_current(task_id, plan_id, revision, expected_digest)
        statuses = self._review_statuses(task_id, plan_id, revision)
        steps = tuple(
            self._copy_step(step, revision + 1, review_status=statuses.get(step.step_id, step.review_status))
            for step in current.steps
        )
        return self._append_revision(
            task_id, current, principal, expected_digest, steps, summary=summary, reason=reason,
        )

    def _decision(
        self, task_id: str, plan_id: str, revision: int, principal: str,
        expected_digest: str, decision: str, *, step_id: str | None = None,
        reason: str | None = None,
    ) -> PlanReviewDecision:
        current = self._exact_current(task_id, plan_id, revision, expected_digest)
        if step_id is not None and step_id not in {step.step_id for step in current.steps}:
            raise KeyError(step_id)
        try:
            return self.store.record_plan_decision(
                task_id, plan_id, revision, decision, principal=principal,
                expected_plan_digest=expected_digest, step_id=step_id, reason=reason,
            )
        except ConcurrencyConflict as error:
            raise PlanConflict(str(error), self.store.plan(task_id, plan_id)) from error

    def _exact_current(
        self, task_id: str, plan_id: str, revision: int, expected_digest: str,
    ) -> PlanRevision:
        current = self.store.plan(task_id, plan_id)
        if current.revision != revision or current.canonical_digest != expected_digest:
            raise PlanConflict("plan revision or digest is stale", current)
        return current

    def _append_revision(
        self, task_id: str, current: PlanRevision, principal: str, expected_digest: str,
        steps: tuple[PlannedStep, ...], *, summary: str, reason: str,
    ) -> PlanRevision:
        self._validate_steps(steps)
        payload = current.model_dump(mode="python", exclude={"canonical_digest", "steps"})
        payload.update({
            "revision": current.revision + 1,
            "parent_revision": current.revision,
            "summary": summary,
            "author": RevisionAuthor.user,
            "revision_reason": reason,
            "review_status": PlanReviewStatus.in_review,
            "steps": steps,
        })
        revised = PlanRevision.model_validate(payload)
        try:
            return self.store.append_plan(
                task_id, revised, expected_current_digest=expected_digest,
            )
        except ConcurrencyConflict as error:
            raise PlanConflict(str(error), self.store.plan(task_id, current.plan_id)) from error

    def _validate_steps(self, steps: tuple[PlannedStep, ...]) -> None:
        for step in steps:
            if not self.registry.has_capability(step.capability_id):
                raise ValueError(f"unknown capability: {step.capability_id}")

    def _review_statuses(self, task_id: str, plan_id: str, revision: int) -> dict[str, StepReviewStatus]:
        statuses: dict[str, StepReviewStatus] = {}
        for decision in self.store.plan_decisions(task_id, plan_id, revision):
            if decision.step_id is not None:
                statuses[decision.step_id] = (
                    StepReviewStatus.approved if decision.decision == "approve" else StepReviewStatus.rejected
                )
        return statuses

    @staticmethod
    def _dependents(steps: tuple[PlannedStep, ...], changed: str) -> set[str]:
        invalidated: set[str] = set()
        progressed = True
        while progressed:
            progressed = False
            for step in steps:
                if step.step_id not in invalidated and any(
                    dependency == changed or dependency in invalidated for dependency in step.dependencies
                ):
                    invalidated.add(step.step_id)
                    progressed = True
        return invalidated

    @staticmethod
    def _effect(operation: str, connector: object) -> EffectClass:
        if connector is not None and operation not in _EFFECTS:
            return EffectClass.external_effect
        return _EFFECTS.get(operation, EffectClass.command)

    @staticmethod
    def _copy_step(step: PlannedStep, revision: int, **updates: object) -> PlannedStep:
        payload = step.model_dump(mode="python", exclude={"canonical_digest"})
        payload.update(updates)
        payload["plan_revision"] = revision
        return PlannedStep.model_validate(payload)

    @staticmethod
    def _copy_plan(plan: PlanRevision, **updates: object) -> PlanRevision:
        payload = plan.model_dump(mode="python", exclude={"canonical_digest"})
        payload.update(updates)
        return PlanRevision.model_validate(payload)
