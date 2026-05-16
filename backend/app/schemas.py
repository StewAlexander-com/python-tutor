from typing import Literal, Optional

from pydantic import BaseModel, Field


Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    model: Optional[str] = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)
    system: Optional[str] = None
    stream: bool = False


class ChatResponse(BaseModel):
    model: str
    message: ChatMessage
    done: bool = True
    eval_count: Optional[int] = None
    prompt_eval_count: Optional[int] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama_reachable: bool
    ollama_url: str
    default_model: str
    model_available: Optional[bool] = None
    available_models: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class ConfigResponse(BaseModel):
    ollama_url: str
    default_model: str
    request_timeout: float
