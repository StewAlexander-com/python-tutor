import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "tutor-system-prompt.md"

# Fallback system prompt if the prompt file cannot be read.
FALLBACK_SYSTEM_PROMPT = (
    "You are an offline Python tutor. Teach with hints first. "
    "Do not solve the whole problem unless the learner asks. "
    "Be concise, precise, and never claim code ran without runtime evidence."
)


def _extract_prompt_body(text: str) -> str:
    """Extract the first fenced code block from the tutor prompt markdown.

    The repo's prompts/tutor-system-prompt.md wraps the canonical system prompt
    in a ```text fence. If no fence is found we return the file contents as-is.
    """
    start = text.find("```")
    if start == -1:
        return text.strip()
    newline = text.find("\n", start)
    if newline == -1:
        return text.strip()
    end = text.find("```", newline + 1)
    if end == -1:
        return text[newline + 1 :].strip()
    return text[newline + 1 : end].strip()


def load_system_prompt() -> str:
    path = Path(os.getenv("TUTOR_SYSTEM_PROMPT_PATH", str(DEFAULT_SYSTEM_PROMPT_PATH)))
    try:
        return _extract_prompt_body(path.read_text(encoding="utf-8"))
    except OSError:
        return FALLBACK_SYSTEM_PROMPT


@dataclass(frozen=True)
class Settings:
    ollama_url: str
    model: str
    request_timeout: float
    allow_origins: tuple[str, ...]
    serve_frontend: bool
    frontend_dir: Path
    system_prompt: str


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def get_settings() -> Settings:
    return Settings(
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        model=os.getenv("TUTOR_MODEL", "gemma3:4b"),
        request_timeout=float(os.getenv("TUTOR_REQUEST_TIMEOUT", "120")),
        allow_origins=_split_csv(
            os.getenv(
                "TUTOR_ALLOW_ORIGINS",
                "http://localhost:8000,http://127.0.0.1:8000",
            )
        ),
        serve_frontend=os.getenv("TUTOR_SERVE_FRONTEND", "0") == "1",
        frontend_dir=Path(os.getenv("TUTOR_FRONTEND_DIR", str(REPO_ROOT / "frontend"))),
        system_prompt=load_system_prompt(),
    )
