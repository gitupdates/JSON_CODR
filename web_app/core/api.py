from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from web_app.core.artifact_store import ArtifactStore
from web_app.core.contracts import TaskCommand, TaskStatus
from web_app.core.policy import PolicyService
from web_app.core.plan_service import PlanConflict, PlanService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore
from web_app.core.component_manager import ComponentManager
from web_app.core.component_registry import ComponentRequest, ComponentScope


Runtime = tuple[CoreService, TaskStore, PolicyService]
RuntimeProvider = Callable[[], Runtime]
PlanServiceProvider = Callable[[], PlanService]


class SteeringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=262_144)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str = Field(min_length=1, max_length=512)


class ComponentInstallApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PlanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: str | None = Field(default=None, max_length=4096)


class StepEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    changes: dict[str, Any]


class PlanReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    summary: str = Field(max_length=8192)
    reason: str = Field(min_length=1, max_length=2048)


class PolicyApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class BaselineRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    project_root: str = Field(min_length=1, max_length=4096)


def create_core_router(
    runtime: RuntimeProvider,
    *,
    artifact_store: Callable[[], ArtifactStore] | None = None,
    capabilities: Callable[[], Sequence[Mapping[str, Any]]] = tuple,
    components: Callable[[], ComponentManager] | None = None,
    plan_service: PlanServiceProvider | None = None,
    project_adapter: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    def plans() -> PlanService:
        if plan_service is None:
            raise HTTPException(status_code=503, detail={
                "type": "about:blank", "title": "Plan service unavailable", "status": 503,
            })
        return plan_service()

    def plan_result(call):
        try:
            return call()
        except PlanConflict as error:
            raise HTTPException(status_code=409, detail={
                "type": "urn:json-codr:plan-conflict", "title": "Plan conflict", "status": 409,
                "detail": str(error), "current_revision": error.current_revision,
                "current_digest": error.current_digest,
            }) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail={
                "type": "urn:json-codr:not-found", "title": "Plan not found", "status": 404,
            }) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail={
                "type": "urn:json-codr:invalid-plan-edit", "title": "Invalid plan edit", "status": 422,
                "detail": str(error),
            }) from error

    @router.get("/api/tasks/{task_id}/plans")
    def list_plans(task_id: str):
        try:
            return runtime()[1].plans(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/approve")
    def approve_plan(
        task_id: str, plan_id: str, revision: int, request: PlanDecisionRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        return plan_result(lambda: plans().approve_plan(
            task_id, plan_id, revision, principal, request.expected_plan_digest,
        ))

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/reject")
    def reject_plan(
        task_id: str, plan_id: str, revision: int, request: PlanDecisionRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        if not request.reason:
            raise HTTPException(status_code=422, detail={
                "type": "urn:json-codr:invalid-plan-decision", "title": "Reason required", "status": 422,
            })
        return plan_result(lambda: plans().reject_plan(
            task_id, plan_id, revision, principal, request.expected_plan_digest, request.reason,
        ))

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/steps/{step_id}/approve")
    def approve_step(
        task_id: str, plan_id: str, revision: int, step_id: str, request: PlanDecisionRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        return plan_result(lambda: plans().approve_step(
            task_id, plan_id, revision, step_id, principal, request.expected_plan_digest,
        ))

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/steps/{step_id}/reject")
    def reject_step(
        task_id: str, plan_id: str, revision: int, step_id: str, request: PlanDecisionRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        if not request.reason:
            raise HTTPException(status_code=422, detail={
                "type": "urn:json-codr:invalid-plan-decision", "title": "Reason required", "status": 422,
            })
        return plan_result(lambda: plans().reject_step(
            task_id, plan_id, revision, step_id, principal, request.expected_plan_digest, request.reason,
        ))

    @router.patch("/api/tasks/{task_id}/plans/{plan_id}/{revision}/steps/{step_id}")
    def edit_step(
        task_id: str, plan_id: str, revision: int, step_id: str, request: StepEditRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        return plan_result(lambda: plans().edit_step(
            task_id, plan_id, revision, step_id, principal,
            request.expected_plan_digest, request.changes,
        ))

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/revise")
    def revise_plan(
        task_id: str, plan_id: str, revision: int, request: PlanReviseRequest,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        return plan_result(lambda: plans().revise_plan(
            task_id, plan_id, revision, principal, request.expected_plan_digest,
            summary=request.summary, reason=request.reason,
        ))

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/policy")
    def apply_policy(
        task_id: str, plan_id: str, revision: int, request: PolicyApplyRequest,
    ):
        return plan_result(lambda: plans().apply_policy(
            task_id, plan_id, revision, request.expected_plan_digest,
            policy_digest=request.policy_digest,
        ))

    @router.post("/api/tasks/{task_id}/plans/{plan_id}/{revision}/baseline")
    def refresh_baseline(
        task_id: str, plan_id: str, revision: int, request: BaselineRefreshRequest,
    ):
        if project_adapter is None:
            raise HTTPException(status_code=503, detail={
                "type": "about:blank", "title": "Project adapter unavailable", "status": 503,
            })
        return plan_result(lambda: plans().refresh_baseline(
            task_id, plan_id, revision, request.expected_plan_digest,
            project_adapter=project_adapter(), project_root=request.project_root,
        ))

    @router.post("/api/components/plan")
    def plan_component(request: ComponentRequest):
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        return components().plan(request)

    @router.post("/api/components/install/{plan_id}")
    def install_component(plan_id: str, approval: ComponentInstallApproval):
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

    @router.post("/api/components/{component_id}/disable")
    def disable_component(component_id: str, scope: ComponentScope = ComponentScope.global_, project_id: str | None = None):
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        components().disable(component_id, scope, project_id)
        return {"status": "disabled", "component_id": component_id}

    @router.post("/api/components/{component_id}/rollback")
    def rollback_component(component_id: str, scope: ComponentScope = ComponentScope.global_, project_id: str | None = None):
        if components is None:
            raise HTTPException(status_code=503, detail="component registry unavailable")
        return components().rollback(component_id, scope, project_id)

    @router.post("/api/tasks")
    async def submit_task(
        command: TaskCommand,
        response: Response,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        record = await runtime()[0].submit(command, principal=principal)
        if record.events and record.events[-1].event_type == "task.permission_required":
            response.status_code = 202
        return record

    @router.post("/api/tasks/live", status_code=202)
    async def start_task(
        command: TaskCommand,
        principal: Annotated[str, Header(alias="X-JSON-CODR-Principal")] = "user",
    ):
        return await runtime()[0].start(command, principal=principal)

    @router.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return runtime()[1].get(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @router.get("/api/tasks/{task_id}/events")
    def get_events(task_id: str, after_sequence: int = -1):
        try:
            return runtime()[0].subscribe(task_id, after_sequence)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

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
