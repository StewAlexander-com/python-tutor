"""FastAPI application exposing tutor endpoints backed by a local Ollama server."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import docs_refs
from .config import Settings, get_settings
from .exercises import Exercise, grade, load_exercises
from .ollama_client import OllamaClient, OllamaError
from .runner import (
    DEFAULT_TIMEOUT_SEC,
    MAX_CODE_BYTES,
    STRICT_IMPORTS,
    RunnerError,
    run_python,
)
from .schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    DocReference,
    DocsBlock,
    DocsLookupRequest,
    DocsLookupResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExerciseDetail,
    ExerciseSummary,
    GradeRequest,
    GradeResponse,
    HealthResponse,
    RunRequest,
    RunResponse,
    TestOutcomeModel,
)


def _ensure_system_prompt(
    messages: list[ChatMessage], system: str | None, default_system: str
) -> list[ChatMessage]:
    if messages and messages[0].role == "system":
        return messages
    prompt = system if system is not None else default_system
    return [ChatMessage(role="system", content=prompt), *messages]


def _exercise_summary(ex: Exercise) -> ExerciseSummary:
    return ExerciseSummary(
        id=ex.id,
        title=ex.title,
        section=ex.section,
        concepts=list(ex.concepts),
    )


def _exercise_detail(ex: Exercise) -> ExerciseDetail:
    return ExerciseDetail(
        id=ex.id,
        title=ex.title,
        section=ex.section,
        concepts=list(ex.concepts),
        prompt=ex.prompt,
        starter_code=ex.starter_code,
        visible_tests=list(ex.visible_tests),
        references=list(ex.references),
    )


def _docs_to_block(lookup: docs_refs.DocsLookup) -> DocsBlock:
    return DocsBlock(
        references=[
            DocReference(label=r.label, url=r.url, source=r.source)
            for r in lookup.refs
        ],
        online=lookup.online,
        online_ok=lookup.online_ok,
        note=lookup.note,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Python Tutor Backend",
        version="0.2.0",
        description="Local-first tutor API that proxies an Ollama-compatible LLM (e.g. Gemma).",
    )

    exercises = load_exercises()

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
            docs_online=docs_refs.online_enabled(),
            docs_timeout=docs_refs.online_timeout(),
            docs_allowlist=sorted(docs_refs.allowed_hosts()),
            exercises_loaded=len(exercises),
            strict_imports=STRICT_IMPORTS,
        )

    def _result_to_response(result) -> RunResponse:
        return RunResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            truncated=result.truncated,
            blocked=getattr(result, "blocked", False),
            safety_events=list(getattr(result, "safety_events", []) or []),
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

    # ----- exercises ------------------------------------------------------

    @app.get("/api/exercises", response_model=list[ExerciseSummary])
    async def list_exercises() -> list[ExerciseSummary]:
        return [_exercise_summary(ex) for ex in exercises.values()]

    @app.get("/api/exercises/{exercise_id}", response_model=ExerciseDetail)
    async def get_exercise(exercise_id: str) -> ExerciseDetail:
        ex = exercises.get(exercise_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="exercise not found")
        return _exercise_detail(ex)

    @app.post("/api/exercises/{exercise_id}/grade", response_model=GradeResponse)
    async def grade_exercise(exercise_id: str, req: GradeRequest) -> GradeResponse:
        ex = exercises.get(exercise_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="exercise not found")
        try:
            result = await grade(
                ex,
                req.code,
                include_hidden=req.include_hidden,
                timeout=req.timeout,
            )
        except RunnerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return GradeResponse(
            exercise_id=ex.id,
            all_passed=result.all_passed,
            visible=[TestOutcomeModel(**asdict(o)) for o in result.visible],
            hidden=[TestOutcomeModel(**asdict(o)) for o in result.hidden],
            run=_result_to_response(result.run),
        )

    # ----- docs reference lookup -----------------------------------------

    @app.post("/api/docs/lookup", response_model=DocsLookupResponse)
    async def docs_lookup(req: DocsLookupRequest) -> DocsLookupResponse:
        lookup = await docs_refs.lookup(
            code=req.code,
            question=req.question,
            section=req.section,
            concepts=req.concepts,
            verify_online=req.verify_online,
        )
        block = _docs_to_block(lookup)
        return DocsLookupResponse(**block.model_dump())

    # ----- evaluate ------------------------------------------------------

    def _build_evaluation_prompt(
        code: str,
        run_resp: RunResponse,
        section: str | None,
        question: str | None,
        docs: DocsBlock,
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
        if docs.references:
            lines.append(
                "  4. If you cite documentation, use only URLs from the"
                " 'Reference material' list below. Do not invent links."
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
        if run_resp.blocked:
            lines.append(
                "NOTE: the static safety scanner blocked execution; see"
                " safety_events."
            )
        lines.append("Stdout:")
        lines.append("```")
        lines.append(run_resp.stdout or "(empty)")
        lines.append("```")
        lines.append("Stderr:")
        lines.append("```")
        lines.append(run_resp.stderr or "(empty)")
        lines.append("```")
        if docs.references:
            lines.append("")
            lines.append("Reference material (curated, on the docs allowlist):")
            for ref in docs.references:
                lines.append(f"- {ref.label} — {ref.url}")
            if docs.note:
                lines.append(f"(note: {docs.note})")
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

        # Pull reference material from the curated layer. Online check
        # honours TUTOR_DOCS_ONLINE; we never block on network failure.
        docs_lookup = await docs_refs.lookup(
            code=req.code,
            question=req.question,
            section=req.section,
        )
        docs_block = _docs_to_block(docs_lookup)

        prompt = _build_evaluation_prompt(
            req.code, run_resp, req.section, req.question, docs_block
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
            docs=docs_block,
        )

    # ----- chat ----------------------------------------------------------

    def _augment_chat_with_docs(
        messages: list[ChatMessage], docs: DocsBlock
    ) -> list[ChatMessage]:
        """If we found credible references for the user's last turn, append a
        compact note to the system message so the model can cite them. We do
        not edit user-authored content."""
        if not docs.references:
            return messages
        lines = ["Reference material available (on the docs allowlist):"]
        for ref in docs.references:
            lines.append(f"- {ref.label} — {ref.url}")
        lines.append(
            "If you cite documentation, only use these URLs verbatim. Do not"
            " invent or paraphrase links."
        )
        note = "\n".join(lines)
        if messages and messages[0].role == "system":
            head = messages[0]
            new_head = ChatMessage(
                role="system", content=head.content.rstrip() + "\n\n" + note
            )
            return [new_head, *messages[1:]]
        return [ChatMessage(role="system", content=note), *messages]

    async def _docs_for_chat(messages: list[ChatMessage]) -> DocsBlock:
        # Use only the last user turn for token extraction — that keeps
        # references tightly scoped and avoids leaking earlier topics.
        last_user = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user = m.content
                break
        if not last_user.strip():
            return DocsBlock()
        lookup = await docs_refs.lookup(code=None, question=last_user)
        return _docs_to_block(lookup)

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        model = req.model or settings.model
        messages = _ensure_system_prompt(req.messages, req.system, settings.system_prompt)
        docs_block = await _docs_for_chat(messages)
        messages = _augment_chat_with_docs(messages, docs_block)

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
                # Append a final "docs" frame so clients can render
                # references even when streaming.
                if docs_block.references:
                    tail = {
                        "docs": docs_block.model_dump(),
                        "done": True,
                    }
                    yield (json.dumps(tail) + "\n").encode("utf-8")

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
            docs=docs_block,
        )

    if settings.serve_frontend and settings.frontend_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(settings.frontend_dir), html=True),
            name="frontend",
        )

    return app


app = create_app()
