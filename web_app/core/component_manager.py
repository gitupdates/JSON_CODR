from __future__ import annotations

import shutil
from pathlib import Path
import json

from web_app.core.component_acquisition import AcquiredComponent, ComponentAcquirer
from web_app.core.component_catalog import ComponentCatalog
from web_app.core.component_inspection import ComponentInspector
from web_app.core.component_probe import ComponentProbe
from web_app.core.component_registry import ComponentPlan, ComponentRegistry, ComponentRequest, ComponentScope
from web_app.core.component_runtime import ComponentRuntimeInstaller
from web_app.core.component_shims import ShimManager


class ComponentManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry = ComponentRegistry(self.root / "registry.sqlite")
        self.acquirer = ComponentAcquirer()
        self.inspector = ComponentInspector(self.registry)
        self.installer = ComponentRuntimeInstaller()
        self.probe = ComponentProbe()
        self.catalog = ComponentCatalog(self.registry)
        self.shims = ShimManager(self.root / "shims")
        self._acquired: dict[str, AcquiredComponent] = {}
        self.pending = self.root / "pending"
        self.pending.mkdir(exist_ok=True)
        self.registry.recover()
        self.installer.recover(self.root / "runtimes")

    def close(self) -> None:
        self.registry.close()

    def plan(self, request: ComponentRequest) -> ComponentPlan:
        acquired = self.acquirer.acquire(request, self.root / "staging")
        plan = self.inspector.inspect(acquired, request.scope, project_id=request.project_id)
        self._acquired[plan.plan_id] = acquired
        (self.pending / f"{plan.plan_id}.json").write_text(acquired.model_dump_json(), encoding="utf-8")
        return plan

    def install(self, plan_id: str, approved_digest: str) -> dict:
        request = self.registry.request_for_plan(plan_id)
        if self.registry.plan_digest(plan_id) != approved_digest:
            raise PermissionError("approved component plan digest does not match")
        acquired = self._acquired.pop(plan_id, None)
        pending = self.pending / f"{plan_id}.json"
        if acquired is None and pending.is_file():
            acquired = AcquiredComponent.model_validate_json(pending.read_text(encoding="utf-8"))
        if acquired is None:
            raise KeyError(plan_id)
        plan = self.inspector.inspect(acquired, request.scope, project_id=request.project_id)
        generation = self.registry.stage(plan)
        try:
            runtime = self.installer.install(plan, acquired.source_root, self.root / "runtimes")
            observation = self.probe.probe(plan, runtime)
            verified = self.registry.record_probe(
                plan.component_id, generation.generation, succeeded=observation.succeeded,
                evidence_digest=observation.evidence_digest,
                reason=None if observation.succeeded else observation.output,
                runtime_root=runtime.runtime_root,
            )
            if not observation.succeeded:
                return {"status": "quarantined", "generation": verified.model_dump(mode="json")}
            if request.activation:
                self.registry.activate(plan.component_id, generation.generation, scope=request.scope, project_id=request.project_id)
            self.refresh_shims()
            return {"status": "active" if request.activation else "verified", "generation": verified.model_dump(mode="json")}
        finally:
            shutil.rmtree(acquired.source_root, ignore_errors=True)
            pending.unlink(missing_ok=True)

    def list(self, project_id: str) -> tuple[dict, ...]:
        return tuple(item.model_dump(mode="json") for item in self.catalog.resolve_components(project_id))

    def disable(self, component_id: str, scope: ComponentScope, project_id: str | None = None) -> None:
        self.registry.disable(component_id, scope=scope, project_id=project_id)
        self.refresh_shims()

    def rollback(self, component_id: str, scope: ComponentScope, project_id: str | None = None) -> dict:
        result = self.registry.rollback(component_id, scope=scope, project_id=project_id)
        self.refresh_shims()
        return result.model_dump(mode="json")

    def refresh_shims(self) -> None:
        components = {item.component_id: item.commands for item in self.catalog.resolve_components("")}
        self.shims.refresh(components)
