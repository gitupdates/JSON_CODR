from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from web_app.core.artifact_store import ArtifactStore
from web_app.core.contracts import TaskCommand, TaskStatus
from web_app.core.policy import PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


Runtime = tuple[CoreService, TaskStore, PolicyService]
RuntimeProvider = Callable[[], Runtime]


class SteeringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=262_144)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str = Field(min_length=1, max_length=512)


def create_core_router(
    runtime: RuntimeProvider,
    *,
    artifact_store: Callable[[], ArtifactStore] | None = None,
    capabilities: Callable[[], Sequence[Mapping[str, Any]]] = tuple,
) -> APIRouter:
    router = APIRouter()

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
        try:
            while True:
                request = await websocket.receive_json()
                task_id = request.get("task_id")
                after_sequence = request.get("after_sequence", -1)
                if not isinstance(task_id, str) or not isinstance(after_sequence, int):
                    await websocket.send_json({"error": "invalid event subscription"})
                    continue
                try:
                    events = runtime()[0].subscribe(task_id, after_sequence)
                except KeyError:
                    await websocket.send_json({"error": "task not found", "task_id": task_id})
                    continue
                await websocket.send_json(
                    {"task_id": task_id, "events": [event.model_dump(mode="json") for event in events]}
                )
        except WebSocketDisconnect:
            return

    return router
