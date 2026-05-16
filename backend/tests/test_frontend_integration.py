"""Integration-shaped smoke tests that verify the frontend chat module is
wired to the backend correctly.

These tests do not require a running Ollama — they assert on:
  * Static frontend mount when TUTOR_SERVE_FRONTEND=1.
  * The chat JS/CSS assets exist and are referenced from index.html.
  * The chat JS calls POST /api/chat with a JSON body matching the
    ChatRequest schema.
  * The service worker bypasses /api/* requests.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import REPO_ROOT, Settings
from app.main import create_app


FRONTEND_DIR = REPO_ROOT / "frontend"


def _settings(**overrides) -> Settings:
    base = dict(
        ollama_url="http://ollama.test",
        model="gemma3:4b",
        request_timeout=5.0,
        allow_origins=("http://localhost:8000",),
        serve_frontend=True,
        frontend_dir=FRONTEND_DIR,
        system_prompt="You are a Python tutor.",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client_with_frontend() -> TestClient:
    return TestClient(create_app(_settings()))


def test_chat_assets_exist() -> None:
    assert (FRONTEND_DIR / "tutor-chat.js").is_file()
    assert (FRONTEND_DIR / "tutor-chat.css").is_file()


def test_index_html_references_chat_assets() -> None:
    index = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert 'href="tutor-chat.css' in index
    assert 'src="tutor-chat.js' in index
    assert 'meta name="tutor-backend"' in index


def test_chat_js_posts_to_api_chat() -> None:
    js = (FRONTEND_DIR / "tutor-chat.js").read_text(encoding="utf-8")
    # The module must POST to /api/chat with a JSON body containing `messages`.
    assert "/api/chat" in js
    assert "method: 'POST'" in js or 'method: "POST"' in js
    assert "application/json" in js
    assert "messages" in js
    # And it should also probe /api/health.
    assert "/api/health" in js


def test_service_worker_bypasses_api_calls() -> None:
    sw = (FRONTEND_DIR / "sw.js").read_text(encoding="utf-8")
    # The bypass must short-circuit before the cache logic.
    assert "/api/" in sw
    assert re.search(r"pathname\.startsWith\(['\"]/api/['\"]\)", sw)


def test_frontend_index_served_when_serve_frontend(client_with_frontend: TestClient) -> None:
    resp = client_with_frontend.get("/")
    assert resp.status_code == 200
    assert "Offline Python Tutor" in resp.text
    assert "tutor-chat.js" in resp.text


def test_frontend_static_assets_served(client_with_frontend: TestClient) -> None:
    for path in ("/tutor-chat.js", "/tutor-chat.css", "/app.js", "/sw.js"):
        resp = client_with_frontend.get(path)
        assert resp.status_code == 200, path
        assert resp.content, path


def test_api_routes_still_work_alongside_frontend(client_with_frontend: TestClient) -> None:
    resp = client_with_frontend.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["default_model"] == "gemma3:4b"


@respx.mock
def test_chat_endpoint_accepts_frontend_payload_shape(client_with_frontend: TestClient) -> None:
    """Round-trip the exact JSON shape tutor-chat.js sends."""
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {"role": "assistant", "content": "Let's start by printing the list."},
                "done": True,
            },
        )
    )
    payload = {
        "messages": [
            {"role": "user", "content": 'Context: I am currently reading "Section 03 — Lists".\n\nWhy is my list empty?'},
        ]
    }
    resp = client_with_frontend.post("/api/chat", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"]["role"] == "assistant"
    assert "print" in body["message"]["content"]


def test_cors_allows_configured_origin() -> None:
    settings = _settings(allow_origins=("http://localhost:8000",), serve_frontend=False)
    client = TestClient(create_app(settings))
    resp = client.options(
        "/api/chat",
        headers={
            "origin": "http://localhost:8000",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"
