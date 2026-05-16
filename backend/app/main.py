"""FastAPI application exposing tutor endpoints backed by a local Ollama server."""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .ollama_client import OllamaClient, OllamaError
from .schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    HealthResponse,
)


def _ensure_system_prompt(
    messages: list[ChatMessage], system: str | None, default_system: str
) -> list[ChatMessage]:
    if messages and messages[0].role == "system":
        return messages
    prompt = system if system is not None else default_system
    return [ChatMessage(role="system", content=prompt), *messages]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Python Tutor Backend",
        version="0.1.0",
        description="Local-first tutor API that proxies an Ollama-compatible LLM (e.g. Gemma).",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allow_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    def make_client() -> OllamaClient:
        return OllamaClient(settings.ollama_url, settings.request_timeout)

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        client = make_client()
        try:
            models = await client.list_models()
        except Exception as exc:  # noqa: BLE001 - surface as degraded
            return HealthResponse(
                status="degraded",
                ollama_reachable=False,
                ollama_url=settings.ollama_url,
                default_model=settings.model,
                error=str(exc),
            )
        return HealthResponse(
            status="ok",
            ollama_reachable=True,
            ollama_url=settings.ollama_url,
            default_model=settings.model,
            model_available=settings.model in models,
            available_models=models,
        )

    @app.get("/api/config", response_model=ConfigResponse)
    async def config() -> ConfigResponse:
        return ConfigResponse(
            ollama_url=settings.ollama_url,
            default_model=settings.model,
            request_timeout=settings.request_timeout,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        model = req.model or settings.model
        messages = _ensure_system_prompt(req.messages, req.system, settings.system_prompt)

        if req.stream:
            async def event_stream() -> AsyncIterator[bytes]:
                client = make_client()
                try:
                    async for chunk in client.chat_stream(
                        model=model,
                        messages=messages,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                    ):
                        yield (json.dumps(chunk) + "\n").encode("utf-8")
                except OllamaError as exc:
                    err = {"error": str(exc)}
                    yield (json.dumps(err) + "\n").encode("utf-8")

            return StreamingResponse(event_stream(), media_type="application/x-ndjson")

        client = make_client()
        try:
            raw = await client.chat(
                model=model,
                messages=messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
        except OllamaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        msg = raw.get("message") or {}
        content = msg.get("content", "")
        return ChatResponse(
            model=raw.get("model", model),
            message=ChatMessage(role="assistant", content=content),
            done=bool(raw.get("done", True)),
            eval_count=raw.get("eval_count"),
            prompt_eval_count=raw.get("prompt_eval_count"),
        )

    if settings.serve_frontend and settings.frontend_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(settings.frontend_dir), html=True),
            name="frontend",
        )

    return app


app = create_app()
