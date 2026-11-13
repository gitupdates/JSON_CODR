from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    model: str
    prompt: str


class ChatResult(BaseModel):
    model: str
    status: str
    summary: str
    content: str
    error: Optional[str] = None


class ModelInfo(BaseModel):
    name: str
    installed: bool
    size: Optional[int] = None
    quantization: Optional[str] = None
    context_length: Optional[int] = None
    capabilities: List[str] = []
