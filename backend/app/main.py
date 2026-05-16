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
from .runner import (
    DEFAULT_TIMEOUT_SEC,
    MAX_CODE_BYTES,
    RunnerError,
    run_python,
)
from .schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    RunRequest,
    RunResponse,
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
            run_timeout_default=DEFAULT_TIMEOUT_SEC,
            run_max_code_bytes=MAX_CODE_BYTES,
        )

    def _result_to_response(result) -> RunResponse:
        return RunResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            truncated=result.truncated,
        )

    @app.post("/api/run", response_model=RunResponse)
    async def run(req: RunRequest) -> RunResponse:
        try:
            result = await run_python(
                req.code, stdin=req.stdin, timeout=req.timeout
            )
        except RunnerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _result_to_response(result)

    def _build_evaluation_prompt(
        code: str,
        run_resp: RunResponse,
        section: str | None,
        question: str | None,
    ) -> str:
        # Build a compact, factual evidence packet. The LLM is told to act
        # on these facts and not to invent runtime behaviour.
        lines: list[str] = []
        lines.append(
            "You are reviewing a student's Python attempt. Use only the runtime"
            " evidence below — do not claim outputs or behaviour you can't see."
            " Reply in three short parts:"
        )
        lines.append("  1. Assessment — one line: passed | needs_work | error.")
        lines.append(
            "  2. Feedback — 2-4 sentences, hint-first. If the code errored,"
            " explain the error in beginner terms. If it ran cleanly, judge"
            " whether the approach is right; otherwise give a hint, not a fix."
        )
        lines.append(
            "  3. Next step — one short concrete suggestion (a small change to"
            " try, or a follow-up exercise)."
        )
        lines.append("")
        if section:
            lines.append(f'Section context: "{section}".')
        if question:
            lines.append(f"Student question: {question}")
        lines.append("")
        lines.append("Student code:")
        lines.append("```python")
        lines.append(code)
        lines.append("```")
        lines.append("")
        lines.append(f"Exit code: {run_resp.exit_code}")
        lines.append(f"Duration: {run_resp.duration_ms} ms")
        if run_resp.timed_out:
            lines.append("NOTE: execution hit the runner's timeout.")
        lines.append("Stdout:")
        lines.append("```")
        lines.append(run_resp.stdout or "(empty)")
        lines.append("```")
        lines.append("Stderr:")
        lines.append("```")
        lines.append(run_resp.stderr or "(empty)")
        lines.append("```")
        return "\n".join(lines)

    def _classify_assessment(text: str, run_resp: RunResponse) -> str:
        """Best-effort parse of the model's first line; fall back to evidence."""
        first = (text or "").strip().splitlines()[0].lower() if text else ""
        for label in ("passed", "needs_work", "needs work", "error"):
            if label in first:
                return "needs_work" if label == "needs work" else label
        if run_resp.timed_out or run_resp.exit_code != 0:
            return "error" if run_resp.stderr else "needs_work"
        return "needs_work"

    def _extract_next_step(text: str) -> str | None:
        if not text:
            return None
        for line in text.splitlines():
            stripped = line.strip().lstrip("-*0123456789. ").strip()
            low = stripped.lower()
            if low.startswith("next step"):
                # "Next step: ..." or "Next step — ..."
                for sep in (":", "—", "-"):
                    if sep in stripped:
                        return stripped.split(sep, 1)[1].strip() or None
                return stripped
        return None

    @app.post("/api/evaluate", response_model=EvaluateResponse)
    async def evaluate(req: EvaluateRequest) -> EvaluateResponse:
        if req.run_output is not None:
            run_resp = req.run_output
        else:
            try:
                result = await run_python(
                    req.code, stdin=req.stdin, timeout=None
                )
            except RunnerError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            run_resp = _result_to_response(result)

        prompt = _build_evaluation_prompt(
            req.code, run_resp, req.section, req.question
        )
        model = req.model or settings.model
        messages = [
            ChatMessage(role="system", content=settings.system_prompt),
            ChatMessage(role="user", content=prompt),
        ]
        client = make_client()
        try:
            raw = await client.chat(
                model=model,
                messages=messages,
                temperature=req.temperature,
            )
        except OllamaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        msg = raw.get("message") or {}
        feedback = msg.get("content", "") or ""
        return EvaluateResponse(
            assessment=_classify_assessment(feedback, run_resp),
            feedback=feedback,
            next_step=_extract_next_step(feedback),
            run=run_resp,
            model=raw.get("model", model),
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
