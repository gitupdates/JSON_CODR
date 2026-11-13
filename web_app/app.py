from fastapi import FastAPI, HTTPException

from web_app.models import ChatRequest, ChatResult
from web_app.ollama_service import (
    ModelOutputError,
    ModelTimeoutError,
    OllamaService,
    OllamaUnavailableError,
)


def create_app(service: OllamaService) -> FastAPI:
    application = FastAPI(title="JSON_CODR", version="V1.0.0")

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
