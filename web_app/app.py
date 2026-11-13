from pathlib import Path

import asyncio

from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from web_app.attachments import AttachmentService, AttachmentTooLarge
from web_app.artifacts import ArtifactService
from web_app.context import ContextAssembler
from web_app.dependencies import DependencyService
from web_app.models import AttachmentUpdate, ChatMessage, ChatRequest, ChatResult, ClipboardTextRequest, DiscoveryInstallRequest, KnownSkillScanRequest, SettingsUpdate, SkillPackRenameRequest, SkillScanRequest, SkillSelectionRequest, SkillUpdateRequest, TerminalCreateRequest
from web_app.ollama_service import (
    ModelOutputError,
    ModelTimeoutError,
    OllamaService,
    OllamaUnavailableError,
)
from web_app.workspace import InvalidSessionId, WorkspaceService, default_data_root
from web_app.terminal import TerminalService
from web_app.skills import DuplicateSkillPack, SkillConverterService, SkillDiscoveryService, SkillLibraryService
from web_app.settings import SettingsService


def create_app(
    service: OllamaService,
    workspace: WorkspaceService | None = None,
    attachments: AttachmentService | None = None,
    terminals: TerminalService | None = None,
) -> FastAPI:
    application = FastAPI(title="JSON_CODR", version="V1.0.3")
    workspace = workspace or WorkspaceService(default_data_root())
    attachments = attachments or AttachmentService(workspace)
    skill_library = SkillLibraryService(workspace.data_root)
    skill_library.ensure_envelopes()
    skill_converter = SkillConverterService()
    settings = SettingsService(workspace.data_root)
    skill_discovery = SkillDiscoveryService(skill_library, skill_converter, workspace.data_root)
    context_assembler = ContextAssembler(attachments, skills=skill_library)
    dependency_service = DependencyService(attachments)
    artifact_service = ArtifactService(workspace)
    terminals = terminals or TerminalService()
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

    @application.get("/api/settings")
    async def get_settings():
        return settings.get()

    @application.patch("/api/settings")
    async def update_settings(request: SettingsUpdate):
        return settings.update(request)

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

    @application.get("/api/sessions/{session_id}/attachments/{attachment_id}/original")
    async def download_original(session_id: str, attachment_id: str):
        try:
            path, record = attachments.original_path(session_id, attachment_id)
            return FileResponse(
                path,
                media_type="application/octet-stream",
                filename=record.display_name,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.post("/api/sessions/{session_id}/attachments/{attachment_id}/retry")
    async def retry_attachment(session_id: str, attachment_id: str):
        try:
            return attachments.retry(session_id, attachment_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.get("/api/sessions/{session_id}/archive.zip")
    async def export_session_archive(session_id: str):
        try:
            payload = attachments.export_zip(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="json-codr-{session_id}.zip"'},
        )

    @application.get("/api/skills")
    async def list_skills():
        return skill_library.list()

    @application.get("/api/skills/standard/envelope.md")
    async def download_skill_envelope_standard():
        path = Path(__file__).resolve().parent.parent / "docs" / "user" / "json-codr-skill-envelope.md"
        return FileResponse(path, media_type="text/markdown", filename="json-codr-skill-envelope.md")

    @application.get("/api/skills/standard/envelope.schema.json")
    async def download_skill_envelope_schema():
        path = Path(__file__).resolve().parent.parent / "docs" / "user" / "json-codr-skill-envelope.schema.json"
        return FileResponse(path, media_type="application/schema+json", filename="json-codr-skill-envelope.schema.json")

    @application.post("/api/skills/scan")
    async def scan_skills(request: SkillScanRequest):
        try:
            result = skill_discovery.scan(request.directory)
            current = settings.get()
            if str(Path(request.directory).resolve()) not in current.skill_scan.approved_directories:
                current.skill_scan.approved_directories.append(str(Path(request.directory).resolve()))
                settings.update(SettingsUpdate(skill_scan=current.skill_scan))
            return result
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/scan-known")
    async def scan_known_skills(request: KnownSkillScanRequest):
        try:
            return skill_discovery.scan_known(request.fallback_token)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/install-discovery", status_code=201)
    async def install_discovered_skill(request: DiscoveryInstallRequest):
        try:
            return skill_discovery.install(request.discovery_id)
        except DuplicateSkillPack as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get("/api/skills/{pack_id}/{skill_id}/documentation.md")
    async def download_skill_documentation(pack_id: str, skill_id: str):
        try:
            document = skill_library.documentation(pack_id, skill_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill not found") from error
        return PlainTextResponse(
            document,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{skill_id}.md"'},
        )

    def convert_attachment(session_id: str, attachment_id: str):
        path, record = attachments.original_path(session_id, attachment_id)
        return skill_converter.convert(path, record.display_name)

    @application.post("/api/sessions/{session_id}/attachments/{attachment_id}/skill-preview")
    async def preview_skill_pack(session_id: str, attachment_id: str):
        try:
            return convert_attachment(session_id, attachment_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/sessions/{session_id}/attachments/{attachment_id}/skill-install", status_code=201)
    async def install_skill_pack(session_id: str, attachment_id: str):
        try:
            return skill_library.install(convert_attachment(session_id, attachment_id))
        except DuplicateSkillPack as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/deduplicate")
    async def deduplicate_skills():
        result = skill_library.deduplicate()
        for pack_id in result["removed_pack_ids"]:
            workspace.clear_skill_pack(pack_id)
        return result

    @application.patch("/api/sessions/{session_id}/skills")
    async def select_session_skills(session_id: str, request: SkillSelectionRequest):
        try:
            session = workspace.get_session(session_id)
            for selection in request.selected:
                if ":" not in selection:
                    raise ValueError("Invalid skill selection")
                skill = skill_library.get_skill(*selection.split(":", 1))
                if not skill.enabled:
                    raise ValueError("Disabled skills cannot be selected")
            session.selected_skill_ids = list(dict.fromkeys(request.selected))
            workspace.save_manifest(session)
            return session
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill or session not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.patch("/api/skills/{pack_id}/{skill_id}")
    async def update_skill(pack_id: str, skill_id: str, request: SkillUpdateRequest):
        try:
            updated = skill_library.update_skill(pack_id, skill_id, request.content, request.enabled)
            if request.session_id:
                session = workspace.get_session(request.session_id)
                selection = f"{pack_id}:{skill_id}"
                selected = [item for item in session.selected_skill_ids if item != selection]
                if request.enabled:
                    selected.append(selection)
                session.selected_skill_ids = selected
                workspace.save_manifest(session)
            return updated
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill or session not found") from error

    @application.patch("/api/skills/{pack_id}")
    async def rename_skill_pack(pack_id: str, request: SkillPackRenameRequest):
        try:
            return skill_library.rename(pack_id, request.name)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill pack not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.delete("/api/skills/{pack_id}", status_code=204)
    async def remove_skill_pack(pack_id: str):
        try:
            skill_library.remove(pack_id)
            workspace.clear_skill_pack(pack_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill pack not found") from error
        return Response(status_code=204)

    @application.get("/api/sessions/{session_id}/artifacts/{filename}")
    async def download_artifact(session_id: str, filename: str):
        try:
            path = artifact_service.artifact_path(session_id, filename)
            return FileResponse(path, media_type="application/zip", filename=filename)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Artifact not found") from error

    @application.get("/api/sessions/{session_id}/dependencies")
    async def detect_dependencies(session_id: str):
        try:
            return dependency_service.detect(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

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

    def require_terminal_header(x_json_codr: str | None) -> None:
        if x_json_codr != "1":
            raise HTTPException(status_code=403, detail="Terminal request header required")

    @application.get("/api/terminals")
    async def list_terminals():
        return terminals.list()

    @application.post("/api/terminals", status_code=201)
    async def create_terminal(request: TerminalCreateRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        cwd = Path(request.cwd).resolve() if request.cwd else Path(__file__).resolve().parent.parent
        try:
            return terminals.create(request.shell, cwd)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/terminals/{terminal_id}/interrupt", status_code=204)
    async def interrupt_terminal(terminal_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            terminals.interrupt(terminal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Terminal not found") from error
        return Response(status_code=204)

    @application.delete("/api/terminals/{terminal_id}", status_code=204)
    async def close_terminal(terminal_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            terminals.close(terminal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Terminal not found") from error
        return Response(status_code=204)

    @application.websocket("/ws/terminals/{terminal_id}")
    async def terminal_socket(websocket: WebSocket, terminal_id: str):
        expected_origin = f"http://{websocket.url.hostname}:{websocket.url.port}"
        if websocket.headers.get("origin") != expected_origin:
            await websocket.close(code=1008)
            return
        try:
            terminals.get(terminal_id)
        except KeyError:
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def send_output():
            while terminals.get(terminal_id).status == "running":
                output = await asyncio.to_thread(terminals.read, terminal_id, 0.2)
                if output:
                    await websocket.send_json({"type": "output", "data": output})
            await websocket.send_json({"type": "exit"})

        async def receive_input():
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "input":
                    terminals.write(terminal_id, str(message.get("data", "")))
                elif message.get("type") == "interrupt":
                    terminals.interrupt(terminal_id)

        sender = asyncio.create_task(send_output())
        receiver = asyncio.create_task(receive_input())
        try:
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        except WebSocketDisconnect:
            pass

    @application.post("/api/chat", response_model=ChatResult)
    async def chat(request: ChatRequest, http_request: Request):
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
            conversion_words = ("convert", "save", "archive")
            wants_conversion = all(word in original_prompt.casefold() for word in conversion_words)
            source_archive = next(
                (
                    item for item in (session.attachments if request.session_id else [])
                    if item.included and item.detected_type in {"application/zip", "application/x-7z-compressed"}
                ),
                None,
            )
            if wants_conversion and source_archive:
                bundle = await service.convert_archive(request.model, model_prompt)
                artifact = artifact_service.save_conversion(
                    request.session_id,
                    source_archive.display_name,
                    bundle.files,
                )
                artifact.url = str(
                    http_request.url_for(
                        "download_artifact",
                        session_id=request.session_id,
                        filename=artifact.filename,
                    )
                )
                result = ChatResult(
                    model=request.model,
                    status="success",
                    summary=bundle.summary,
                    content=(
                        f"Converted files: {len(bundle.files)}\n"
                        f"Saved archive: {artifact.filename}\n"
                        f"Hard drive: {artifact.path}\n"
                        f"Download URL: {artifact.url}"
                    ),
                    artifact=artifact,
                )
            else:
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
