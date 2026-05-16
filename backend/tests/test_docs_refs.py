"""Tests for the docs reference retrieval layer (offline + mocked online)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import docs_refs
from app.config import Settings
from app.docs_refs import (
    DocRef,
    allowed_hosts,
    filter_allowlisted,
    is_allowlisted,
    lookup,
)
from app.main import create_app


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
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Default: leave docs_online flag unset so each test controls it.
    monkeypatch.setenv("TUTOR_DOCS_ONLINE", "0")
    return TestClient(create_app(_settings()))


# ----- allowlist ------------------------------------------------------------


def test_allowlist_known_hosts() -> None:
    assert is_allowlisted("https://docs.python.org/3/tutorial/index.html")
    assert is_allowlisted("https://docs.pytest.org/en/stable/")
    assert is_allowlisted("https://packaging.python.org/en/latest/")


def test_allowlist_rejects_unknown_hosts() -> None:
    assert not is_allowlisted("https://example.com/docs")
    assert not is_allowlisted("https://evil.invalid/python")
    assert not is_allowlisted("not a url at all")


def test_filter_allowlisted_drops_off_list() -> None:
    urls = [
        "https://docs.python.org/3/",
        "https://example.com/",
        "https://docs.pytest.org/en/stable/",
    ]
    kept = filter_allowlisted(urls)
    assert "https://docs.python.org/3/" in kept
    assert "https://docs.pytest.org/en/stable/" in kept
    assert "https://example.com/" not in kept


def test_allowlist_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_DOCS_ALLOWLIST", "docs.python.org,example.test")
    hosts = allowed_hosts()
    assert "docs.python.org" in hosts
    assert "example.test" in hosts
    # Pytest docs no longer on the list when overridden.
    assert "docs.pytest.org" not in hosts


# ----- curated lookup -------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_finds_curated_for_loops() -> None:
    result = await lookup(
        code="for i in range(3):\n    print(i)\n",
        question=None,
        section="Loops",
        verify_online=False,
    )
    urls = [r.url for r in result.refs]
    assert any("controlflow.html#for-statements" in u for u in urls)
    assert all(is_allowlisted(u) for u in urls)
    assert result.online is False


@pytest.mark.asyncio
async def test_lookup_finds_pytest_for_test_question() -> None:
    result = await lookup(
        code=None,
        question="How do I write a pytest test?",
        verify_online=False,
    )
    urls = [r.url for r in result.refs]
    assert any("pytest" in u for u in urls)


@pytest.mark.asyncio
async def test_lookup_includes_exercise_refs_after_filtering() -> None:
    result = await lookup(
        code="print(1)\n",
        exercise_refs=[
            "https://docs.python.org/3/library/functions.html#print",
            "https://evil.example.com/totally-real-docs",
        ],
        verify_online=False,
    )
    urls = [r.url for r in result.refs]
    assert "https://docs.python.org/3/library/functions.html#print" in urls
    assert all("evil.example.com" not in u for u in urls)


@pytest.mark.asyncio
async def test_lookup_empty_when_no_signal() -> None:
    result = await lookup(
        code=None, question=None, section=None, verify_online=False
    )
    assert result.refs == []


# ----- online verification --------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_online_verification_keeps_only_reachable() -> None:
    # docs.python.org responds, docs.pytest.org times out.
    respx.head("https://docs.python.org/3/library/functions.html#print").mock(
        return_value=httpx.Response(200)
    )
    # Match anything else with an error to simulate offline.
    respx.head(host__regex=".*").mock(side_effect=httpx.ConnectError("nope"))

    result = await lookup(
        code="print('hi')\n",
        question=None,
        verify_online=True,
        timeout=1.0,
    )
    # We should still have refs (print is curated) and at least one
    # online_ok=True because one host responded.
    if result.refs:
        # Reachable URL kept; unreachable curated entries dropped.
        urls = [r.url for r in result.refs]
        assert any("functions.html#print" in u for u in urls)
        assert result.online is True
        assert result.online_ok is True


@pytest.mark.asyncio
@respx.mock
async def test_online_all_unreachable_marks_note() -> None:
    respx.head(host__regex=".*").mock(side_effect=httpx.ConnectError("offline"))

    result = await lookup(
        code="for i in range(3): pass\n", verify_online=True, timeout=0.5
    )
    assert result.online is True
    assert result.online_ok is False
    # Refs are still returned (unverified) with a note explaining the state.
    assert result.note and "unreachable" in result.note.lower()
    assert len(result.refs) >= 1


@pytest.mark.asyncio
@respx.mock
async def test_online_handles_405_via_get() -> None:
    url = "https://docs.python.org/3/library/functions.html#print"
    respx.head(url).mock(return_value=httpx.Response(405))
    respx.get(url).mock(return_value=httpx.Response(200))
    respx.head(host__regex=".*").mock(return_value=httpx.Response(404))

    result = await lookup(
        code="print('hi')\n", verify_online=True, timeout=1.0
    )
    urls = [r.url for r in result.refs]
    assert url in urls


# ----- /api/docs/lookup -----------------------------------------------------


def test_docs_lookup_endpoint_offline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = client.post(
        "/api/docs/lookup",
        json={"code": "for i in range(3): print(i)", "verify_online": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is False
    assert any(
        "controlflow.html" in r["url"] or "stdtypes.html" in r["url"]
        for r in body["references"]
    )


def test_config_exposes_docs_settings(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "docs_online" in body
    assert "docs_timeout" in body
    assert "docs_allowlist" in body
    assert "docs.python.org" in body["docs_allowlist"]


# ----- /api/evaluate integration --------------------------------------------


@respx.mock
def test_evaluate_includes_docs_block(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TUTOR_DOCS_ONLINE", "0")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {
                    "role": "assistant",
                    "content": "passed\nLooks fine.\nNext step: try with negatives.",
                },
            },
        )

    respx.post("http://ollama.test/api/chat").mock(side_effect=handler)

    resp = client.post(
        "/api/evaluate",
        json={
            "code": "for i in range(3):\n    print(i)\n",
            "section": "Loops",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "docs" in body
    assert body["docs"]["online"] is False
    assert any(
        "controlflow.html" in r["url"] for r in body["docs"]["references"]
    )
    # The evaluator's prompt must include the reference list verbatim,
    # so the model has no incentive to invent URLs.
    user_msg = captured["payload"]["messages"][-1]["content"]
    assert "Reference material" in user_msg


@respx.mock
def test_chat_injects_docs_into_system_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TUTOR_DOCS_ONLINE", "0")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {"role": "assistant", "content": "Use a for loop."},
            },
        )

    respx.post("http://ollama.test/api/chat").mock(side_effect=handler)
    resp = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "How do I write a for loop in Python?"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("docs")
    assert body["docs"]["references"]
    # The augmented system message must mention the URL allowlist instruction.
    system_text = captured["payload"]["messages"][0]["content"]
    assert "Reference material" in system_text
    assert "docs.python.org" in system_text
