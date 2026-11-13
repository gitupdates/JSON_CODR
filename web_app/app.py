from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web_app.models import ChatRequest, ChatResult
from web_app.ollama_service import (
    ModelOutputError,
    ModelTimeoutError,
    OllamaService,
    OllamaUnavailableError,
)
from web_app.workspace import InvalidSessionId, WorkspaceService, default_data_root


def create_app(
    service: OllamaService,
    workspace: WorkspaceService | None = None,
) -> FastAPI:
    application = FastAPI(title="JSON_CODR", version="V1.0.0")
    workspace = workspace or WorkspaceService(default_data_root())
    web_root = Path(__file__).resolve().parent.parent / "web"
    application.mount("/static", StaticFiles(directory=web_root), name="static")

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(web_root / "index.html")

    @application.get("/api/health")
    async def health():
        result = await service.health()
        return {"status": "ready" if result["ollama"] else "degraded", **result}

    @application.get("/api/models")
    async def models():
        try:
            return {"models": await service.list_models()}
        except OllamaUnavailableError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.post("/api/sessions", status_code=201)
    async def create_session():
        return workspace.create_session()

    @application.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        try:
            return workspace.get_session(session_id)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        try:
            workspace.delete_session(session_id)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        return Response(status_code=204)

    @application.post("/api/chat", response_model=ChatResult)
    async def chat(request: ChatRequest):
        if not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt must not be empty")
        try:
            return await service.chat(request.model, request.prompt.strip())
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ModelTimeoutError as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
        except ModelOutputError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except OllamaUnavailableError as error:
            status = 409 if str(error) == "Model is not installed" else 502
            raise HTTPException(status_code=status, detail=str(error)) from error

    return application


app = create_app(OllamaService())
