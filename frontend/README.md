# Offline Python Tutor — Frontend

A static, dependency-free single-page web app that serves as the learner-facing UI for the Offline Python Tutor framework. The frontend code was adapted from the [Python Power User](https://github.com/StewAlexander-com/Python-Power-User) project (MIT) and reskinned to fit the tutor concept described in the repository's top-level [README](../README.md) and [architecture docs](../docs/architecture.md).

It runs entirely in the browser, loads `content/sections.json` over `fetch`, and ships with a service worker so it works offline once cached. It does not require a backend to display content. Future work will wire it up to the local LLM adapter, sandbox runner, and learner-state store described in the framework docs.

## What is in here

```
frontend/
├── index.html          # SPA shell, hash routing (#/, #/beginner, #/power, #/s/<key>)
├── app.js              # Router, renderer, lightweight Python syntax highlighter
├── tutor-chat.js       # Floating chat panel that calls POST /api/chat
├── tutor-codelab.js    # Inline code lab (Run / Evaluate + references)
├── base.css            # Reset + base typography
├── style.css           # Theme and layout
├── tutor-chat.css      # Chat panel styles
├── tutor-codelab.css   # Code-lab styles
├── manifest.json       # PWA manifest
├── sw.js               # Service worker (cache-first shell, SWR for the rest)
├── 404.html            # GitHub Pages SPA hash redirect helper
├── robots.txt
├── content/
│   └── sections.json   # 46 Python sections (goal, prompts, demo source)
└── assets/
    ├── favicon.svg
    ├── icons/          # PWA icons (72–512 px)
    └── screenshots/    # PWA screenshots + OG image
```

The data in `content/sections.json` was generated from `python_poweruser.py` in the upstream project. It contains the Python sections only — no executable backend.

## Run it locally

The app is static. Any HTTP server will do — but you **must** serve it over `http://` (not `file://`) for `fetch()` and the service worker to work.

Pick whichever is convenient:

```bash
# Python 3 (no dependencies)
cd frontend
python3 -m http.server 8000
# then open http://localhost:8000/
```

```bash
# Node (if you have npx)
cd frontend
npx --yes serve -l 8000 .
```

```bash
# Caddy / nginx / any other static server pointed at frontend/
```

Hard refresh (`Ctrl/Cmd+Shift+R`) after editing static assets, or unregister the service worker in DevTools, since `sw.js` aggressively caches the shell.

## Routes

The app uses hash routing so it works from any path:

- `#/` — home, pick a learning path
- `#/beginner` — full section browser, beginner mode
- `#/power` — full section browser, quick-reference mode
- `#/s/<section-key>` — a single section (e.g. `#/s/variables`)

## Hooking it up to the tutor backend

The first piece of tutor interactivity is in [`tutor-chat.js`](tutor-chat.js):
a floating "Ask tutor" panel that POSTs the running message history to the
backend's [`/api/chat`](../backend/README.md#post-apichat) endpoint and renders
the assistant reply (markdown-ish — fenced code blocks and inline backticks
are recognised). When a section is open, its number and title are prepended to
the user message as lightweight context.

### Backend URL resolution

The chat module looks up the backend URL in this order:

1. `window.TUTOR_BACKEND_URL` (set by an inline `<script>` before `tutor-chat.js`)
2. `<meta name="tutor-backend" content="...">` in `index.html`
3. `localStorage.getItem('tutor-backend')`
4. Heuristic: if the page is on `localhost:<other port>`, assume the backend is on `:8001`
5. Same origin (empty string) — used when the backend serves the frontend with `TUTOR_SERVE_FRONTEND=1`

### Service-worker bypass

`sw.js` explicitly bypasses any same-origin URL starting with `/api/`, so
chat requests always hit the live FastAPI server even when the rest of the
shell is served from cache.

### Inline code lab — read · run · evaluate

Each section view also mounts an inline **code lab** ([`tutor-codelab.js`](tutor-codelab.js))
beneath the lesson body. It seeds an editor with the section's example
snippet and adds two actions:

- **Run** — POSTs `{code, timeout?}` to [`/api/run`](../backend/README.md#post-apirun)
  and shows stdout, stderr, exit code, duration, and a timeout flag.
- **Evaluate** — POSTs `{code, section, question?, run_output?}` to
  [`/api/evaluate`](../backend/README.md#post-apievaluate). The backend
  builds an evidence packet (the code plus the *actual* runtime output)
  and asks the local LLM for a hint-first assessment with a concrete
  next step.

The lab reuses chat-panel design tokens (amber accent, dark surfaces,
mono labels). A small "prototype safety · subprocess + timeout" pill is
always visible next to **Run** so the safety surface is honest.
See [`docs/ux-workflow.md`](../docs/ux-workflow.md) for the candidate
workflows considered and the chosen blend.

### Reference material

Both the evaluation card and chat responses now include a **References**
block when the backend's curated docs lookup matches the topic. URLs come
from `docs.python.org`, `docs.pytest.org`, `packaging.python.org`, and the
other allowlisted sources defined in
[`backend/app/docs_refs.py`](../backend/app/docs_refs.py). When network
verification is on (`TUTOR_DOCS_ONLINE=1`, the default), each URL is
HEAD-checked; the UI labels the block `verified live`, `offline ·
unverified`, or `offline` accordingly. No URLs are generated by the LLM —
the model can only cite from the supplied list.

### Still to come

1. Streaming responses for `/api/evaluate` (the chat endpoint already supports `stream: true` NDJSON).
2. Per-exercise integration in the lesson view (the backend already
   exposes `GET /api/exercises` and grading).
3. A learner-state read/write layer talking to a small local store.

Keeping the frontend static means it can be hosted next to the backend as a `file://`-equivalent app, embedded in a desktop shell, or served by the tutor process itself.

## Provenance and license

- Frontend HTML/CSS/JS, PWA assets, and `content/sections.json` were copied and lightly adapted from [Python Power User](https://github.com/StewAlexander-com/Python-Power-User) (MIT, © Stew Alexander). The upstream repository is **not** modified by this project — it is used as a source only.
- Branding, copy, manifest metadata, service-worker cache key, and the 404 SPA-redirect base path were changed to fit this repository.
