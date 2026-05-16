# Python Tutor Backend

A small, local-first FastAPI service that proxies an [Ollama](https://ollama.com)-compatible
LLM (default: `gemma3:4b`) and exposes a tutor-shaped HTTP API for the
[`frontend/`](../frontend/) PWA and other clients.

The backend is intentionally minimal. It does not yet execute student code; the
sandboxed runner described in [`docs/safety-and-sandboxing.md`](../docs/safety-and-sandboxing.md)
is a separate milestone.

## Layout

```
backend/
├── app/
│   ├── config.py         # env-driven Settings + tutor system prompt loader
│   ├── main.py           # FastAPI app factory and routes
│   ├── ollama_client.py  # async client for /api/tags and /api/chat
│   └── schemas.py        # pydantic request/response models
├── tests/
│   └── test_api.py       # mocked Ollama tests via respx
├── requirements.txt
├── requirements-dev.txt
└── pytest.ini
```

## Prerequisites

- Python 3.10+
- A running Ollama server with a pulled model. For example:
  ```bash
  ollama serve &
  ollama pull gemma3:4b
  ```

## Install

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # runtime only
# or
pip install -r requirements-dev.txt      # runtime + pytest + respx
```

## Run

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Then in another terminal serve the frontend:

```bash
cd frontend
python3 -m http.server 8000
```

Open <http://localhost:8000/> for the UI and <http://localhost:8001/docs> for the
auto-generated OpenAPI explorer.

You can also serve both from a single process by exporting `TUTOR_SERVE_FRONTEND=1`
before launching uvicorn — the static frontend will be mounted at `/`.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Base URL of the Ollama-compatible server. |
| `TUTOR_MODEL` | `gemma3:4b` | Default model name used when a request omits `model`. |
| `TUTOR_REQUEST_TIMEOUT` | `120` | HTTP timeout (seconds) for calls to Ollama. |
| `TUTOR_ALLOW_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Comma-separated CORS origins. |
| `TUTOR_SERVE_FRONTEND` | `0` | Set to `1` to mount `frontend/` at `/`. |
| `TUTOR_FRONTEND_DIR` | `../frontend` | Override the directory used when serving the frontend. |
| `TUTOR_SYSTEM_PROMPT_PATH` | `../prompts/tutor-system-prompt.md` | Markdown file whose first fenced block is used as the default system prompt. |

## Endpoints

### `GET /api/health`

Reports whether Ollama is reachable and whether the default model is installed.

```bash
curl -s http://localhost:8001/api/health | jq
```

```json
{
  "status": "ok",
  "ollama_reachable": true,
  "ollama_url": "http://localhost:11434",
  "default_model": "gemma3:4b",
  "model_available": true,
  "available_models": ["gemma3:4b", "llama3.1:8b"]
}
```

If Ollama is down, the endpoint still returns 200 with `status: "degraded"` so
clients can render a friendly banner.

### `GET /api/config`

Returns the resolved server config (useful for the frontend to know which model
and Ollama URL it is talking to).

### `POST /api/chat`

Generates a tutor response. The backend injects the canonical tutor system
prompt from [`prompts/tutor-system-prompt.md`](../prompts/tutor-system-prompt.md)
unless the request supplies its own `system` value or already starts with a
`system` message.

Request body:

```jsonc
{
  "messages": [
    {"role": "user", "content": "Why does my for-loop print nothing?"}
  ],
  "model": "gemma3:4b",          // optional — defaults to TUTOR_MODEL
  "temperature": 0.2,            // optional
  "max_tokens": 512,             // optional
  "system": "Custom prompt...",  // optional override
  "stream": false                // when true, returns NDJSON chunks
}
```

Example:

```bash
curl -s http://localhost:8001/api/chat \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"What is a list comprehension?"}]}' | jq
```

Streaming variant:

```bash
curl -N http://localhost:8001/api/chat \
  -H 'content-type: application/json' \
  -d '{"stream":true,"messages":[{"role":"user","content":"hi"}]}'
```

Each streamed line is a JSON object forwarded from Ollama's `/api/chat` stream.

## Tests

```bash
cd backend
.venv/bin/pytest -q
```

Tests use `respx` to mock the Ollama HTTP API, so they run without a real model
server. The suite covers health (reachable + degraded), config, default and
custom system prompt injection, and upstream error handling.

## Roadmap

- Add a `/api/run` endpoint that wraps the sandboxed Python runner described in
  [`docs/safety-and-sandboxing.md`](../docs/safety-and-sandboxing.md).
- Add a `/api/tutor/turn` endpoint that orchestrates: run code → collect
  evidence → call LLM with the structured context template from
  [`prompts/tutor-system-prompt.md`](../prompts/tutor-system-prompt.md).
- Persist learner state (see roadmap M4).
