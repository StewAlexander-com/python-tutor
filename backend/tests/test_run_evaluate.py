"""Tests for the /api/run and /api/evaluate endpoints and the runner module.

These tests run real Python subprocesses (via app.runner) — they are
fast (under a second) and require no Ollama. The /api/evaluate tests
mock the Ollama HTTP layer with respx.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runner import RunnerError, run_python


def _settings(**overrides) -> Settings:
    base = dict(
        ollama_url="http://ollama.test",
        model="gemma3:4b",
        request_timeout=5.0,
        allow_origins=("http://localhost:8000",),
        serve_frontend=False,
        frontend_dir=Path("/tmp/does-not-exist"),
        system_prompt="You are a Python tutor.",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_settings()))


# ----- runner module ---------------------------------------------------------

@pytest.mark.asyncio
async def test_runner_captures_stdout() -> None:
    result = await run_python("print('hello, tutor')\n")
    assert result.exit_code == 0
    assert "hello, tutor" in result.stdout
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.truncated is False


@pytest.mark.asyncio
async def test_runner_captures_syntax_error() -> None:
    result = await run_python("def broken(:\n")
    assert result.exit_code != 0
    assert "SyntaxError" in result.stderr


@pytest.mark.asyncio
async def test_runner_enforces_timeout() -> None:
    # An infinite loop must be killed within the timeout window.
    result = await run_python("while True:\n    pass\n", timeout=0.6)
    assert result.timed_out is True
    assert result.exit_code != 0
    assert "timeout" in result.stderr.lower()


@pytest.mark.asyncio
async def test_runner_truncates_large_output() -> None:
    code = "print('x' * 200000)\n"
    result = await run_python(code)
    assert result.truncated is True
    assert "truncated" in result.stdout


@pytest.mark.asyncio
async def test_runner_rejects_oversized_code() -> None:
    huge = "x = 1\n" * 20_000  # ~120 KB > 50 KB default
    with pytest.raises(RunnerError):
        await run_python(huge)


@pytest.mark.asyncio
async def test_runner_isolates_environment() -> None:
    # User env (e.g. SECRET=...) must not leak into the subprocess.
    import os
    os.environ["TUTOR_TEST_SECRET"] = "leak-me"
    try:
        result = await run_python(
            "import os; print(os.environ.get('TUTOR_TEST_SECRET', 'absent'))\n"
        )
    finally:
        del os.environ["TUTOR_TEST_SECRET"]
    assert "absent" in result.stdout


@pytest.mark.asyncio
async def test_runner_accepts_stdin() -> None:
    result = await run_python(
        "import sys; print('got:', sys.stdin.read().strip())\n",
        stdin="hi there",
    )
    assert "got: hi there" in result.stdout


# ----- /api/run endpoint -----------------------------------------------------

def test_run_endpoint_ok(client: TestClient) -> None:
    resp = client.post("/api/run", json={"code": "print(2 + 2)\n"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["exit_code"] == 0
    assert "4" in body["stdout"]
    assert body["timed_out"] is False


def test_run_endpoint_timeout(client: TestClient) -> None:
    resp = client.post(
        "/api/run",
        json={"code": "while True: pass\n", "timeout": 0.6},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["timed_out"] is True


def test_run_endpoint_rejects_empty_code(client: TestClient) -> None:
    resp = client.post("/api/run", json={"code": ""})
    assert resp.status_code == 422


def test_config_includes_run_limits(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "run_timeout_default" in body
    assert "run_max_code_bytes" in body
    assert body["run_max_code_bytes"] >= 1_000


# ----- /api/evaluate endpoint ------------------------------------------------

@respx.mock
def test_evaluate_runs_code_and_calls_llm(client: TestClient) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {
                    "role": "assistant",
                    "content": (
                        "passed\n"
                        "Your loop accumulates correctly and the output matches.\n"
                        "Next step: try the same with a list comprehension."
                    ),
                },
                "done": True,
            },
        )

    respx.post("http://ollama.test/api/chat").mock(side_effect=handler)

    resp = client.post(
        "/api/evaluate",
        json={
            "code": "print(sum(range(5)))\n",
            "section": "10 — Loops",
            "question": "Is this idiomatic?",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment"] == "passed"
    assert body["run"]["exit_code"] == 0
    assert "10" in body["run"]["stdout"]  # sum(range(5)) == 10
    assert "list comprehension" in (body["next_step"] or "")

    # The LLM prompt must include the section context, the code, and the
    # actual stdout from the runtime — not invented output.
    user_msg = captured["payload"]["messages"][-1]["content"]
    assert "10 — Loops" in user_msg
    assert "print(sum(range(5)))" in user_msg
    assert "10" in user_msg


@respx.mock
def test_evaluate_classifies_error_on_syntax_fail(client: TestClient) -> None:
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {
                    "role": "assistant",
                    "content": "error\nThe parser couldn't read this — there's a missing parameter name.\nNext step: write the function header on a fresh line.",
                },
            },
        )
    )
    resp = client.post(
        "/api/evaluate",
        json={"code": "def broken(:\n", "question": "what's wrong?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment"] == "error"
    assert body["run"]["exit_code"] != 0
    assert "SyntaxError" in body["run"]["stderr"]


@respx.mock
def test_evaluate_uses_supplied_run_output_without_re_running(client: TestClient) -> None:
    """If the frontend already ran the code, /api/evaluate trusts that result
    and does not execute again — important so Run + Evaluate is one trip."""
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {
                    "role": "assistant",
                    "content": "needs_work\nThe printed value is right, but you're not handling negatives.\nNext step: add a guard for n < 0.",
                },
            },
        )
    )
    # Deliberately impossible code paired with a fake "successful" run —
    # if the endpoint re-ran the code, the real run would fail and the
    # response would not see this stdout.
    resp = client.post(
        "/api/evaluate",
        json={
            "code": "import sys; sys.exit('this would error if re-run')\n",
            "run_output": {
                "stdout": "42\n",
                "stderr": "",
                "exit_code": 0,
                "duration_ms": 5,
                "timed_out": False,
                "truncated": False,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment"] == "needs_work"
    assert body["run"]["stdout"] == "42\n"
    assert body["run"]["exit_code"] == 0


@respx.mock
def test_evaluate_returns_502_when_ollama_fails(client: TestClient) -> None:
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(500, text="boom")
    )
    resp = client.post("/api/evaluate", json={"code": "print(1)\n"})
    assert resp.status_code == 502
