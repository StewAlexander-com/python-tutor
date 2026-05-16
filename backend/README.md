# Python Tutor Backend

A small, local-first FastAPI service that proxies an [Ollama](https://ollama.com)-compatible
LLM (default: `gemma3:4b`) and exposes a tutor-shaped HTTP API for the
[`frontend/`](../frontend/) PWA and other clients.

The backend now also exposes a *prototype-grade* Python runner
(`POST /api/run`) and an LLM evaluator (`POST /api/evaluate`) used by the
frontend's inline code lab. The runner uses subprocess isolation with a
hard wall-clock timeout and a restricted env — see
[`docs/safety-and-sandboxing.md`](../docs/safety-and-sandboxing.md) for the
controls a real deployment would still need to add.

## Layout

```
backend/
├── app/
│   ├── config.py         # env-driven Settings + tutor system prompt loader
│   ├── main.py           # FastAPI app factory and routes
│   ├── ollama_client.py  # async client for /api/tags and /api/chat
│   ├── runner.py         # prototype Python subprocess runner (timeout + restricted env)
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
| `TUTOR_RUN_TIMEOUT` | `5` | Wall-clock seconds for `/api/run` and `/api/evaluate` code execution. Clamped to 0.5–30s. |
| `TUTOR_RUN_MAX_CODE_BYTES` | `50000` | Max UTF-8 bytes accepted for a single submission. Clamped to 1 000–200 000. |
| `TUTOR_RUN_MAX_OUTPUT_BYTES` | `32000` | Each of stdout/stderr is truncated past this. Clamped to 1 000–200 000. |

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

### `POST /api/run`

Executes student code in an isolated Python subprocess. **Prototype safety
only** — subprocess + hard timeout + restricted env (`python -I`, empty env
except `LC_ALL`/`PYTHONIOENCODING`, temp cwd). This is *not* a real sandbox.

Request:

```jsonc
{
  "code": "print(2 + 2)\n",
  "stdin": "",            // optional
  "timeout": 3.0          // optional, default 5s, clamped 0.5–30s
}
```

Response:

```json
{
  "stdout": "4\n",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 16,
  "timed_out": false,
  "truncated": false
}
```

Errors:

- `400` if `code` exceeds `TUTOR_RUN_MAX_CODE_BYTES`.
- `422` for malformed bodies.
- Student-side failures (syntax errors, non-zero exits, timeouts) are
  **not** errors — they come back in the normal response with
  `exit_code != 0` and/or `timed_out: true`.

### `POST /api/evaluate`

Wraps a `/api/run` + LLM call into one request. Builds a compact evidence
packet (code + actual runtime output + optional section context and
learner question) and asks the tutor model for a hint-first assessment.

Request:

```jsonc
{
  "code": "for n in [1,2,3]: print(n)\n",
  "section": "10 — Loops",            // optional
  "question": "Is this idiomatic?",   // optional
  "run_output": {                     // optional — if present, /api/run is skipped
    "stdout": "...", "stderr": "", "exit_code": 0,
    "duration_ms": 5, "timed_out": false, "truncated": false
  },
  "model": "gemma3:4b",               // optional
  "temperature": 0.2                  // optional
}
```

Response:

```json
{
  "assessment": "passed",
  "feedback": "Your loop iterates correctly and prints each item...",
  "next_step": "Try the same with a list comprehension.",
  "run": { "stdout": "1\n2\n3\n", "stderr": "", "exit_code": 0, "duration_ms": 14, "timed_out": false, "truncated": false },
  "model": "gemma3:4b"
}
```

`assessment` is one of `passed | needs_work | error`. `next_step` is a
best-effort extraction from the model's reply; it may be `null` if the
tutor's response did not include a recognisable next-step line.

## Tests

```bash
cd backend
.venv/bin/pytest -q
```

Tests use `respx` to mock the Ollama HTTP API, so they run without a real model
server. The suite covers health (reachable + degraded), config, default and
custom system prompt injection, upstream error handling, the frontend chat
wiring, and the `/api/run` + `/api/evaluate` endpoints (including the runner
module's timeout, isolation, and output-truncation behaviour).

## Roadmap

- Tighten `/api/run` isolation: container or microVM, network namespace,
  CPU/memory limits, seccomp/AppArmor where available.
- Stream `/api/evaluate` responses (the LLM call already streams; the
  evidence-packet shape just needs an NDJSON variant).
- Persist learner state (see roadmap M4).
