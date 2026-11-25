from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from web_app.core.artifact_store import ArtifactStore
from web_app.core.contracts import PlanRevision, PlannedStep, TaskCommand, TaskEventDraft, TaskStatus
from web_app.core.store import ConcurrencyConflict
from web_app.core.policy import PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore
from web_app.core.component_manager import ComponentManager
from web_app.core.component_registry import ComponentRequest, ComponentScope
from web_app.core.memory import MemoryDraft, MemoryPolicyError, MemoryStore
from web_app.core.http_identity import MutationAuthorizer
from web_app.core.runtime_status import build_runtime_status
from web_app.models import MemorySettings


Runtime = tuple[CoreService, TaskStore, PolicyService]
RuntimeProvider = Callable[[], Runtime]


class SteeringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=262_144)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str = Field(min_length=1, max_length=512)


class TaskApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = Field(pattern=r"^(project|schedule)$")
    proposal_id: str | None = Field(default=None, min_length=1, max_length=200)
    envelope_id: str | None = Field(default=None, min_length=1, max_length=200)


class ComponentInstallApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PlanRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    action: Literal["approve", "edit", "revise", "reject", "request_changes"]
    plan: PlanRevision | None = None
    reason: str | None = Field(default=None, max_length=4096)


class StepRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["approve", "edit", "revise", "reject", "request_changes"]
    step: PlannedStep | None = None
    reason: str | None = Field(default=None, max_length=4096)


class CollectiveMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=65_536)
    source_refs: tuple[str, ...] = ()
    retain_details: bool = False
    idempotency_key: str = Field(min_length=1, max_length=256)


class MemoryRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2048)


def create_core_router(
    runtime: RuntimeProvider,
    *,
    artifact_store: Callable[[], ArtifactStore] | None = None,
    capabilities: Callable[[], Sequence[Mapping[str, Any]]] = tuple,
    components: Callable[[], ComponentManager] | None = None,
    memory_store: Callable[[], MemoryStore] | None = None,
    memory_settings: Callable[[], MemorySettings] = MemorySettings,
    mutation_authorizer: MutationAuthorizer | None = None,
) -> APIRouter:
    router = APIRouter()

    def require_component_mutation(request: Request) -> None:
        if mutation_authorizer is None:
            raise HTTPException(status_code=503, detail="mutation authorization is unavailable")
        mutation_authorizer.principal(request, "component.install")
        mutation_authorizer.csrf(request)

    def require_agent_mutation(request: Request):
        if mutation_authorizer is None:
            raise HTTPException(status_code=503, detail="mutation authorization is unavailable")
        principal = mutation_authorizer.principal(request, "agent.launch")
        mutation_authorizer.csrf(request)
        return principal

    @router.post("/api/components/plan")
    def plan_component(request: ComponentRequest, http_request: Request):
        require_component_mutation(http_request)
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        return components().plan(request)

    @router.post("/api/components/install/{plan_id}")
    def install_component(plan_id: str, approval: ComponentInstallApproval, http_request: Request):
        require_component_mutation(http_request)
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        try:
            return components().install(plan_id, approval.approved_digest)
        except PermissionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="component plan not found") from error

    @router.get("/api/components")
    def list_components(project_id: str = ""):
        return () if components is None else components().list(project_id)

    def memory() -> MemoryStore:
        if memory_store is None:
            raise HTTPException(status_code=503, detail="collective memory unavailable")
        return memory_store()

    @router.post("/api/projects/{project_id}/memory", status_code=201)
    def accept_memory(
        project_id: str,
        request: CollectiveMemoryRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        try:
            configuration = memory_settings()
            if not configuration.enabled:
                raise MemoryPolicyError("collective memory is disabled")
            if request.retain_details and not configuration.detailed_retention_enabled:
                raise MemoryPolicyError("detailed retention is disabled in system settings")
            return memory().accept(MemoryDraft(
                user_id=principal,
                project_id=project_id,
                **request.model_dump(),
            ))
        except MemoryPolicyError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/api/projects/{project_id}/memory/search")
    def search_memory(
        project_id: str,
        query: str = "",
        limit: int | None = None,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        configuration = memory_settings()
        if not configuration.enabled:
            return ()
        effective_limit = configuration.search_limit if limit is None else limit
        return memory().search_collective(principal, project_id, query, max(1, min(effective_limit, 100)))

    @router.get("/api/projects/{project_id}/memory/export")
    def export_memory(
        project_id: str,
        include_inactive: bool = False,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        return memory().export_collective(principal, project_id, include_inactive=include_inactive)

    @router.post("/api/projects/{project_id}/memory/{memory_id}/revoke")
    def revoke_memory(
        project_id: str,
        memory_id: str,
        request: MemoryRevocationRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        try:
            return memory().revoke(
                memory_id, user_id=principal, project_id=project_id, reason=request.reason
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="collective memory not found") from error

    @router.post("/api/components/{component_id}/disable")
    def disable_component(component_id: str, http_request: Request, scope: ComponentScope = ComponentScope.global_, project_id: str | None = None):
        require_component_mutation(http_request)
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        components().disable(component_id, scope, project_id)
        return {"status": "disabled", "component_id": component_id}

    @router.post("/api/components/{component_id}/rollback")
    def rollback_component(component_id: str, http_request: Request, scope: ComponentScope = ComponentScope.global_, project_id: str | None = None):
        require_component_mutation(http_request)
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        return components().rollback(component_id, scope, project_id)

    @router.post("/api/tasks")
    async def submit_task(
        command: TaskCommand,
        response: Response,
        http_request: Request,
    ):
        principal = require_agent_mutation(http_request)
        service = runtime()[0]
        if command.command_type != "agent.run":
            project_root = command.payload.get("project_root")
            if isinstance(project_root, str):
                command = command.model_copy(update={
                    "project_id": service.register_project_root(command.project_id, project_root),
                })
        record = await service.submit(
            command,
            principal=principal.user_id,
            principal_scopes=principal.scopes,
        )
        if record.events and record.events[-1].event_type == "task.permission_required":
            response.status_code = 202
        return record

    @router.post("/api/tasks/live", status_code=202)
    async def start_task(
        command: TaskCommand,
        http_request: Request,
    ):
        principal = require_agent_mutation(http_request)
        service = runtime()[0]
        if command.command_type != "agent.run":
            project_root = command.payload.get("project_root")
            if isinstance(project_root, str):
                command = command.model_copy(update={
                    "project_id": service.register_project_root(command.project_id, project_root),
                })
        return await service.start(
            command,
            principal=principal.user_id,
            principal_scopes=principal.scopes,
        )

    @router.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return runtime()[1].get(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @router.get("/api/tasks/{task_id}/status")
    def get_task_status(task_id: str):
        try:
            record = runtime()[1].get(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error
        return {
            "task_id": record.task_id,
            "status": record.status,
            "permission_required": bool(
                record.events and record.events[-1].event_type == "task.permission_required"
            ),
            "last_sequence": record.events[-1].sequence if record.events else -1,
        }

    @router.get("/api/tasks/{task_id}/result")
    def get_task_result(task_id: str):
        try:
            record = runtime()[1].get(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error
        terminal_events = tuple(
            event for event in record.events if not event.event_type.endswith(".delta")
        )
        return record.model_copy(update={"events": terminal_events})

    @router.get("/api/tasks/{task_id}/events")
    def get_events(task_id: str, after_sequence: int = -1):
        try:
            return runtime()[0].subscribe(task_id, after_sequence)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @router.get("/api/tasks/{task_id}/plans/{plan_id}")
    def get_plan_revisions(task_id: str, plan_id: str):
        return runtime()[1].plan_revisions(task_id, plan_id)

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/revise")
    def revise_plan(task_id: str, plan_id: str, request: PlanRevisionRequest):
        store = runtime()[1]
        current = store.latest_plan(task_id, plan_id)
        if request.expected_revision is not None and (
            current is None or current.revision != request.expected_revision
        ):
            raise HTTPException(status_code=409, detail="plan revision is stale")
        if request.action in {"reject", "request_changes"}:
            return store.append(task_id, TaskEventDraft(
                event_type=f"agent.plan_{request.action}",
                payload={"plan_id": plan_id, "expected_revision": request.expected_revision, "reason": request.reason},
            ))
        if request.action == "approve":
            if current is None:
                raise HTTPException(status_code=404, detail="plan not found")
            store.append(task_id, TaskEventDraft(
                event_type="agent.plan_approved",
                payload={"plan_id": plan_id, "revision": current.revision},
            ))
            return current
        if request.plan is None or request.plan.plan_id != plan_id:
            raise HTTPException(status_code=422, detail="matching plan revision is required")
        try:
            saved = store.save_plan_revision(task_id, request.plan, expected_revision=request.expected_revision)
        except ConcurrencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        store.append(task_id, TaskEventDraft(
            event_type=f"agent.plan_{request.action}",
            payload={"plan_id": plan_id, "revision": saved.revision},
        ))
        return saved

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/steps/{step_id}/revise")
    def revise_step(task_id: str, plan_id: str, step_id: str, request: StepRevisionRequest):
        store = runtime()[1]
        current = store.latest_plan(task_id, plan_id)
        if current is None:
            raise HTTPException(status_code=404, detail="plan not found")
        if current.revision != request.expected_revision:
            raise HTTPException(status_code=409, detail="plan revision is stale")
        if request.action in {"reject", "request_changes"}:
            return store.append(task_id, TaskEventDraft(
                event_type=f"agent.step_{request.action}",
                payload={"plan_id": plan_id, "step_id": step_id, "revision": current.revision, "reason": request.reason},
            ))
        if request.step is None or request.step.step_id != step_id:
            raise HTTPException(status_code=422, detail="matching step revision is required")
        next_revision = current.revision + 1
        replacement = request.step.model_copy(update={"plan_id": plan_id, "plan_revision": next_revision})
        steps = tuple(
            replacement if item.step_id == step_id else item.model_copy(update={"plan_revision": next_revision})
            for item in current.steps
        )
        if not any(item.step_id == step_id for item in current.steps):
            raise HTTPException(status_code=404, detail="step not found")
        revised = PlanRevision(
            plan_id=plan_id, revision=next_revision, goal_id=current.goal_id,
            goal_revision=current.goal_revision, steps=steps,
        )
        store.save_plan_revision(task_id, revised, expected_revision=current.revision)
        store.append(task_id, TaskEventDraft(
            event_type=f"agent.step_{request.action}",
            payload={"plan_id": plan_id, "step_id": step_id, "revision": next_revision,
                     "invalidated_steps": [item.step_id for item in steps if step_id in item.depends_on]},
        ))
        return revised

    @router.post("/api/tasks/{task_id}/steer")
    def steer_task(task_id: str, request: SteeringRequest):
        try:
            return runtime()[0].steer(task_id, request.input)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @router.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str):
        try:
            return runtime()[0].cancel(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @router.post("/api/tasks/{task_id}/approve")
    async def approve_task(
        task_id: str,
        request: TaskApprovalRequest,
        http_request: Request,
    ):
        try:
            principal = require_agent_mutation(http_request)
            return await runtime()[0].approve(
                task_id,
                principal=principal.user_id,
                principal_scopes=principal.scopes,
                scope=request.scope,
                proposal_id=request.proposal_id,
                envelope_id=request.envelope_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @router.post("/api/tasks/{task_id}/retry")
    async def retry_task(
        task_id: str,
        command: TaskCommand,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        if command.parent_task_id != task_id:
            raise HTTPException(status_code=409, detail="retry must reference the original task")
        return await runtime()[0].retry(command, principal=principal)

    @router.post("/api/tasks/{task_id}/restore")
    def restore_task(task_id: str, request: RestoreRequest):
        try:
            runtime()[0].restore(request.checkpoint_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="checkpoint not found") from error
        return {"task_id": task_id, "checkpoint_id": request.checkpoint_id, "status": "restored"}

    @router.get("/api/projects/{project_id}/threads")
    def project_threads(project_id: str):
        records = runtime()[1].for_project(project_id)
        threads: dict[str, dict[str, Any]] = {}
        for record in records:
            entry = threads.setdefault(
                record.thread_id,
                {"thread_id": record.thread_id, "project_id": record.project_id, "tasks": []},
            )
            entry["tasks"].append(record.model_dump(mode="json"))
        return tuple(threads.values())

    @router.get("/api/capabilities")
    def list_capabilities():
        return capabilities()

    @router.get("/api/runtime/telemetry")
    def runtime_telemetry(after_sequence: int = 0):
        return runtime()[1].telemetry(after_sequence)

    @router.get("/api/runtime/heartbeats")
    def runtime_heartbeats():
        return runtime()[1].runtime_heartbeats()

    @router.get("/api/runtime/status")
    def runtime_status():
        store = runtime()[1]
        return build_runtime_status(
            store,
            environment=os.environ,
            current_pid=os.getpid(),
        )

    @router.get("/api/tasks/{task_id}/artifacts/{artifact_id}")
    def download_artifact(task_id: str, artifact_id: str):
        if artifact_store is None:
            raise HTTPException(status_code=404, detail="artifact store unavailable")
        store = artifact_store()
        if not store.belongs_to(task_id, artifact_id):
            raise HTTPException(status_code=403, detail="artifact is not authorized for this task")
        try:
            record = next(item for item in store.export_manifest(task_id) if item["artifact_id"] == artifact_id)
        except (FileNotFoundError, StopIteration) as error:
            raise HTTPException(status_code=404, detail="artifact not found") from error

        def content():
            with store.open(artifact_id) as stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk

        return StreamingResponse(content(), media_type=str(record["media_type"]))

    @router.websocket("/ws/tasks")
    async def task_events(websocket: WebSocket):
        await websocket.accept()
        subscriptions: dict[str, asyncio.Task[None]] = {}
        send_lock = asyncio.Lock()

        async def stream(task_id: str, after_sequence: int) -> None:
            while True:
                events = await runtime()[0].wait_for_events(task_id, after_sequence)
                if events:
                    async with send_lock:
                        await websocket.send_json(
                            {"task_id": task_id, "events": [event.model_dump(mode="json") for event in events]}
                        )
                    after_sequence = events[-1].sequence
                record = runtime()[1].get(task_id)
                if record.status in {
                    TaskStatus.completed,
                    TaskStatus.failed,
                    TaskStatus.cancelled,
                    TaskStatus.interrupted,
                }:
                    return
        try:
            while True:
                request = await websocket.receive_json()
                task_id = request.get("task_id")
                after_sequence = request.get("after_sequence", -1)
                if not isinstance(task_id, str) or not isinstance(after_sequence, int):
                    await websocket.send_json({"error": "invalid event subscription"})
                    continue
                try:
                    runtime()[1].get(task_id)
                except KeyError:
                    await websocket.send_json({"error": "task not found", "task_id": task_id})
                    continue
                previous = subscriptions.pop(task_id, None)
                if previous is not None:
                    previous.cancel()
                subscriptions[task_id] = asyncio.create_task(stream(task_id, after_sequence))
        except WebSocketDisconnect:
            pass
        finally:
            for subscription in subscriptions.values():
                subscription.cancel()
            if subscriptions:
                await asyncio.gather(*subscriptions.values(), return_exceptions=True)

    return router
