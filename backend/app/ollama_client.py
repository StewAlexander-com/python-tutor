"""Thin async client for an Ollama-compatible local LLM server."""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from .schemas import ChatMessage


class OllamaError(RuntimeError):
    """Raised when the Ollama server returns an error or is unreachable."""


class OllamaClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_models(self) -> list[str]:
        url = f"{self.base_url}/api/tags"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    async def ping(self) -> bool:
        try:
            await self.list_models()
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def _build_payload(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: Optional[int],
        stream: bool,
    ) -> dict:
        options: dict = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        return {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "stream": stream,
            "options": options,
        }

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> dict:
        url = f"{self.base_url}/api/chat"
        payload = self._build_payload(model, messages, temperature, max_tokens, stream=False)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Ollama returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Failed to reach Ollama at {self.base_url}: {exc}") from exc

    async def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        url = f"{self.base_url}/api/chat"
        payload = self._build_payload(model, messages, temperature, max_tokens, stream=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Ollama returned {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Failed to reach Ollama at {self.base_url}: {exc}") from exc
