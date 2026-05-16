# Python Tutor Backend

A small, local-first FastAPI service that proxies an [Ollama](https://ollama.com)-compatible
LLM (default: `gemma3:4b`) and exposes a tutor-shaped HTTP API for the
[`frontend/`](../frontend/) PWA and other clients.

The backend exposes:

- `POST /api/chat` and `POST /api/chat` (streaming) — the LLM proxy,
- `POST /api/run` — sandboxed Python execution (timeout + rlimits + static
  scan),
- `POST /api/evaluate` — runs the student's code, looks up curated docs,
  and asks the LLM for hint-first feedback,
- `GET /api/exercises`, `GET /api/exercises/{id}`,
  `POST /api/exercises/{id}/grade` — structured exercises with a
  visible/hidden test split,
- `POST /api/docs/lookup` — curated Python documentation references.

Reference URLs come from a curated allowlist; no LLM-authored URLs are
ever shown. See [Documentation references](#documentation-references) and
[Sandbox controls](#sandbox-controls) below for the policy details.

## Layout

```
backend/
├── app/
│   ├── config.py         # env-driven Settings + tutor system prompt loader
│   ├── main.py           # FastAPI app factory and routes
│   ├── ollama_client.py  # async client for /api/tags and /api/chat
│   ├── runner.py         # prototype Python subprocess runner (timeout + rlimits)
│   ├── safety.py         # static AST scanner — blocks hostile imports / calls
│   ├── docs_refs.py      # curated docs allowlist + optional online HEAD check
│   ├── exercises.py      # JSON exercise loader + grading harness
│   └── schemas.py        # pydantic request/response models
├── tests/
│   ├── test_api.py
│   ├── test_run_evaluate.py
│   ├── test_runner_sandbox.py
│   ├── test_safety.py
│   ├── test_exercises.py
│   └── test_docs_refs.py
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
| `TUTOR_RUN_CPU_SECONDS` | `5` | POSIX `RLIMIT_CPU` (CPU seconds). Clamped 1–60. |
| `TUTOR_RUN_MEM_MB` | `256` | POSIX `RLIMIT_AS` (address space, MB). Clamped 32–4096. |
| `TUTOR_RUN_FSIZE_MB` | `16` | POSIX `RLIMIT_FSIZE` (max file size, MB). Clamped 1–256. |
| `TUTOR_RUN_NPROC` | `64` | POSIX `RLIMIT_NPROC` (max processes). Clamped 8–1024. |
| `TUTOR_STRICT_IMPORTS` | `0` | Also block `os`, `pathlib`, `shutil`, `tempfile`, `glob`, `importlib`, and bare `open(...)`. |
| `TUTOR_DOCS_ONLINE` | `1` | HEAD-check each candidate doc URL before returning it. |
| `TUTOR_DOCS_TIMEOUT` | `2.0` | Online check timeout (s). Clamped 0.5–10. |
| `TUTOR_DOCS_ALLOWLIST` | curated | CSV of allowed doc hostnames; overrides defaults entirely. |
| `TUTOR_EXERCISES_DIR` | repo `curriculum/exercises` | Override exercise directory. |

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
only** — see [Sandbox controls](#sandbox-controls). Static AST scanner runs
first and may short-circuit with `blocked: true`.

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
  "truncated": false,
  "blocked": false,
  "safety_events": []
}
```

When the static scanner refuses execution, `blocked` is true, `exit_code`
is `-1`, and `safety_events` lists each finding (`type`, `detail`,
`lineno`):

```json
{
  "stdout": "",
  "stderr": "[safety] execution blocked: blocked_import: subprocess\n",
  "exit_code": -1,
  "duration_ms": 0,
  "timed_out": false,
  "truncated": false,
  "blocked": true,
  "safety_events": [{"type": "blocked_import", "detail": "subprocess", "lineno": 1}]
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

The `docs` field carries any references found by the lookup pipeline (see
[Documentation references](#documentation-references)). The same evidence
packet is sent to the LLM with the URLs spelled out so the model can cite
them verbatim — and so it has no incentive to invent.

### `GET /api/exercises` and grading

```bash
curl -s http://localhost:8001/api/exercises | jq
curl -s http://localhost:8001/api/exercises/loops.counting-evens | jq
curl -s -X POST http://localhost:8001/api/exercises/loops.counting-evens/grade \
  -H 'content-type: application/json' \
  -d '{"code":"def count_even(numbers):\n    return sum(1 for n in numbers if n%2==0)\n"}' | jq
```

The detail endpoint never exposes `hidden_tests`. The grade endpoint
appends a small JSON-emitting harness to the student's code, runs it
through the sandbox, and reports per-test outcomes; the harness chatter
is stripped from the visible `stdout`.

See [`curriculum/exercises/README.md`](../curriculum/exercises/README.md)
for the exercise schema and authoring rules.

### `POST /api/docs/lookup`

Returns curated reference URLs for a code/question/section without
involving the LLM. Useful for the frontend to surface docs anywhere.

```bash
curl -s http://localhost:8001/api/docs/lookup \
  -H 'content-type: application/json' \
  -d '{"code":"for i in range(3): print(i)", "section":"Loops"}' | jq
```

## Sandbox controls

In addition to the env-var knobs above:

- `python -I -B` (isolated mode, no `.pyc`).
- Environment is hand-built: only `PYTHONIOENCODING`, `PYTHONDONTWRITEBYTECODE`,
  `LC_ALL`, and a placeholder `HOME=/nonexistent` are passed. No `PATH`.
- Per-call tempdir at mode `0o700`, removed after the run.
- POSIX `setrlimit` in a `preexec_fn` for CPU, address space, file size,
  core files, and process count.
- `start_new_session=True` plus `killpg` on timeout so any descendant
  processes die with the parent.
- Static AST scan ([`app/safety.py`](app/safety.py)) — blocks `subprocess`,
  `socket`, `ctypes`, `urllib`, `http`, `pickle`, `multiprocessing`,
  `ssl`, `os.system`, `os.popen`, raw `exec`/`eval`/`__import__`, …
- `TUTOR_STRICT_IMPORTS=1` adds `os`, `pathlib`, `shutil`, `tempfile`,
  `glob`, `importlib`, and bare `open(…)` to the block list.

**Known limits.** None of these defend against kernel-level escape or
side-channel attacks. macOS does not honour `RLIMIT_AS` for Python (we
log + continue). Windows lacks `resource` — the runner still applies the
timeout, env scrubbing, tempdir, and static scan. For multi-tenant or
hostile workloads, run inside a container/microVM/restricted user — see
[`docs/safety-and-sandboxing.md`](../docs/safety-and-sandboxing.md).

## Documentation references

The tutor cites only official Python documentation, and only via URLs
from an allowlist (`docs.python.org`, `packaging.python.org`,
`peps.python.org`, `docs.pytest.org`, `mypy.readthedocs.io`,
`typing.readthedocs.io`, `pip.pypa.io`, `setuptools.pypa.io`, plus the
official sites for NumPy, pandas, Matplotlib, SciPy, Flask, FastAPI,
Django, Requests, HTTPX, SQLAlchemy).

The lookup pipeline:

1. Tokenise the student's code, question, section title, and any
   `concepts` passed in.
2. Match tokens against the curated map in
   [`app/docs_refs.py`](app/docs_refs.py) — only allowlisted URLs.
3. Add exercise-supplied URLs that pass the allowlist filter.
4. If `TUTOR_DOCS_ONLINE=1` (default), issue a HEAD request to each URL
   with `TUTOR_DOCS_TIMEOUT` (default 2s); drop unreachable URLs. If
   every URL fails, return the curated list anyway with `online_ok=false`
   and a note so the UI can label them "unverified".

No URL is ever sourced from the LLM. The evaluation prompt and the chat
system message are explicit: cite only from the supplied list verbatim,
or don't cite.

## Tests

```bash
cd backend
.venv/bin/pytest -q
```

Tests use `respx` to mock the Ollama HTTP API, so they run without a
real model server. The suite covers:

- health (reachable + degraded), config, system-prompt injection, and
  upstream error handling;
- the `/api/run` and `/api/evaluate` endpoints, the runner's timeout,
  environment isolation, output truncation, and oversized-code rejection;
- the **strengthened sandbox controls**: subprocess static-block of
  `subprocess`/`socket`, `PATH` non-propagation, tempdir CWD, and
  (on Linux) the address-space rlimit (`test_runner_sandbox.py`);
- the **safety AST scanner**: hostile imports, dangerous calls, syntax
  errors flagged but not blocked, strict-mode behaviour
  (`test_safety.py`);
- the **exercise schema and grader**: loader validation, allowlist
  filtering of references, passing/failing solutions, runtime errors,
  and the harness output-stripping (`test_exercises.py`);
- the **docs reference layer**: allowlist filtering, curated lookups,
  offline-only behaviour, mocked online HEAD verification with both
  full-success and full-failure cases, the `405 → GET` fallback, the
  `/api/docs/lookup` endpoint, and the `docs` block on `/api/evaluate`
  and `/api/chat` responses (`test_docs_refs.py`).

## Roadmap

- Tighten `/api/run` isolation: container or microVM, network namespace,
  CPU/memory limits, seccomp/AppArmor where available.
- Stream `/api/evaluate` responses (the LLM call already streams; the
  evidence-packet shape just needs an NDJSON variant).
- Persist learner state (see roadmap M4).
