from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(**overrides) -> Settings:
    base = dict(
        ollama_url="http://ollama.test",
        model="gemma3:4b",
        request_timeout=5.0,
        allow_origins=("http://localhost:8000",),
        serve_frontend=False,
        frontend_dir=__import__("pathlib").Path("/tmp/does-not-exist"),
        system_prompt="You are a Python tutor.",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_settings()))


@respx.mock
def test_health_ok(client: TestClient) -> None:
    respx.get("http://ollama.test/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]})
    )
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ollama_reachable"] is True
    assert body["model_available"] is True
    assert body["available_models"] == ["gemma3:4b"]


@respx.mock
def test_health_degraded_when_ollama_down(client: TestClient) -> None:
    respx.get("http://ollama.test/api/tags").mock(
        side_effect=httpx.ConnectError("nope")
    )
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["ollama_reachable"] is False
    assert body["error"]


def test_config_endpoint(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama_url"] == "http://ollama.test"
    assert body["default_model"] == "gemma3:4b"


@respx.mock
def test_chat_injects_system_prompt_and_returns_message(client: TestClient) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = __import__("json").loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {"role": "assistant", "content": "Try printing the value first."},
                "done": True,
                "eval_count": 12,
            },
        )

    respx.post("http://ollama.test/api/chat").mock(side_effect=handler)

    resp = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Why doesn't my loop run?"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"]["content"] == "Try printing the value first."
    assert body["model"] == "gemma3:4b"

    sent_messages = captured["payload"]["messages"]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[0]["content"] == "You are a Python tutor."
    assert sent_messages[1]["role"] == "user"


@respx.mock
def test_chat_preserves_caller_system_prompt(client: TestClient) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = __import__("json").loads(request.content.decode())
        return httpx.Response(
            200,
            json={"model": "gemma3:4b", "message": {"role": "assistant", "content": "ok"}},
        )

    respx.post("http://ollama.test/api/chat").mock(side_effect=handler)

    resp = client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "system", "content": "Custom tutor prompt."},
                {"role": "user", "content": "hi"},
            ]
        },
    )
    assert resp.status_code == 200
    assert captured["payload"]["messages"][0]["content"] == "Custom tutor prompt."


@respx.mock
def test_chat_bad_gateway_on_ollama_error(client: TestClient) -> None:
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(500, text="boom")
    )
    resp = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 502
    assert "Ollama" in resp.json()["detail"]
