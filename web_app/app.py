from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web_app.attachments import AttachmentService, AttachmentTooLarge
from web_app.context import ContextAssembler
from web_app.models import AttachmentUpdate, ChatMessage, ChatRequest, ChatResult, ClipboardTextRequest
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
    attachments: AttachmentService | None = None,
) -> FastAPI:
    application = FastAPI(title="JSON_CODR", version="V1.0.0")
    workspace = workspace or WorkspaceService(default_data_root())
    attachments = attachments or AttachmentService(workspace)
    context_assembler = ContextAssembler(attachments)
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

    @application.get("/api/sessions/{session_id}/attachments")
    async def list_attachments(session_id: str):
        try:
            return workspace.get_session(session_id).attachments
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.post("/api/sessions/{session_id}/attachments", status_code=201)
    async def upload_attachment(session_id: str, file: UploadFile = File(...)):
        try:
            return attachments.import_stream(session_id, file.filename or "attachment", file.file)
        except AttachmentTooLarge as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except (InvalidSessionId, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.post("/api/sessions/{session_id}/clipboard-text", status_code=201)
    async def paste_text(session_id: str, request: ClipboardTextRequest):
        try:
            return attachments.import_text(session_id, request.text)
        except (InvalidSessionId, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.get("/api/sessions/{session_id}/attachments/{attachment_id}/preview")
    async def preview_attachment(session_id: str, attachment_id: str):
        try:
            return attachments.preview(session_id, attachment_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.patch("/api/sessions/{session_id}/attachments/{attachment_id}")
    async def update_attachment(session_id: str, attachment_id: str, request: AttachmentUpdate):
        try:
            return attachments.set_included(session_id, attachment_id, request.included)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.delete("/api/sessions/{session_id}/attachments/{attachment_id}", status_code=204)
    async def delete_attachment(session_id: str, attachment_id: str):
        try:
            attachments.remove(session_id, attachment_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error
        return Response(status_code=204)

    @application.post("/api/chat", response_model=ChatResult)
    async def chat(request: ChatRequest):
        if not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt must not be empty")
        try:
            original_prompt = request.prompt.strip()
            model_prompt = original_prompt
            model_images = []
            if request.session_id:
                session = workspace.get_session(request.session_id)
                model_prompt = context_assembler.build_prompt(session, original_prompt)
                if await service.supports_vision(request.model):
                    model_images = context_assembler.image_paths(session)
            result = await service.chat(request.model, model_prompt, images=model_images)
            if request.session_id:
                workspace.append_message(request.session_id, ChatMessage(role="user", content=original_prompt))
                workspace.append_message(
                    request.session_id,
                    ChatMessage(role="assistant", content=f"{result.summary}\n\n{result.content}"),
                )
            return result
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
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
