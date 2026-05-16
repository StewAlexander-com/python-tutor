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
    docs: Optional["DocsBlock"] = None


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
    run_timeout_default: float = 5.0
    run_max_code_bytes: int = 50_000
    docs_online: bool = True
    docs_timeout: float = 2.0
    docs_allowlist: list[str] = Field(default_factory=list)
    exercises_loaded: int = 0
    strict_imports: bool = False


class RunRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    stdin: str = Field(default="", max_length=200_000)
    timeout: Optional[float] = Field(default=None, ge=0.5, le=30.0)


class SafetyEventModel(BaseModel):
    type: str
    detail: str
    lineno: Optional[int] = None


class RunResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool
    truncated: bool
    blocked: bool = False
    safety_events: list[SafetyEventModel] = Field(default_factory=list)


class EvaluateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    stdin: str = Field(default="", max_length=200_000)
    section: Optional[str] = Field(default=None, max_length=400)
    question: Optional[str] = Field(default=None, max_length=2000)
    run_output: Optional[RunResponse] = None
    model: Optional[str] = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class DocReference(BaseModel):
    label: str
    url: str
    source: Literal["curated", "exercise"] = "curated"


class DocsBlock(BaseModel):
    references: list[DocReference] = Field(default_factory=list)
    online: bool = False
    online_ok: bool = False
    note: Optional[str] = None


class EvaluateResponse(BaseModel):
    assessment: Literal["passed", "needs_work", "error"]
    feedback: str
    next_step: Optional[str] = None
    run: RunResponse
    model: str
    docs: DocsBlock = Field(default_factory=DocsBlock)


class ExerciseSummary(BaseModel):
    id: str
    title: str
    section: str
    concepts: list[str] = Field(default_factory=list)


class ExerciseDetail(ExerciseSummary):
    prompt: str
    starter_code: str
    visible_tests: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class GradeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    timeout: Optional[float] = Field(default=None, ge=0.5, le=30.0)
    include_hidden: bool = True


class TestOutcomeModel(BaseModel):
    expr: str
    passed: bool
    error: Optional[str] = None


class GradeResponse(BaseModel):
    exercise_id: str
    all_passed: bool
    visible: list[TestOutcomeModel] = Field(default_factory=list)
    hidden: list[TestOutcomeModel] = Field(default_factory=list)
    run: RunResponse


class DocsLookupRequest(BaseModel):
    code: Optional[str] = Field(default=None, max_length=200_000)
    question: Optional[str] = Field(default=None, max_length=2000)
    section: Optional[str] = Field(default=None, max_length=400)
    concepts: list[str] = Field(default_factory=list)
    verify_online: Optional[bool] = None


class DocsLookupResponse(DocsBlock):
    pass


ChatResponse.model_rebuild()
