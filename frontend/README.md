# Offline Python Tutor — Frontend

A static, dependency-free single-page web app that serves as the learner-facing UI for the Offline Python Tutor framework. The frontend code was adapted from the [Python Power User](https://github.com/StewAlexander-com/Python-Power-User) project (MIT) and reskinned to fit the tutor concept described in the repository's top-level [README](../README.md) and [architecture docs](../docs/architecture.md).

It runs entirely in the browser, loads `content/sections.json` over `fetch`, and ships with a service worker so it works offline once cached. It does not require a backend to display content. Future work will wire it up to the local LLM adapter, sandbox runner, and learner-state store described in the framework docs.

## What is in here

```
frontend/
├── index.html          # SPA shell, hash routing (#/, #/beginner, #/power, #/s/<key>)
├── app.js              # Router, renderer, lightweight Python syntax highlighter
├── base.css            # Reset + base typography
├── style.css           # Theme and layout
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

The current `app.js` is read-only and self-contained. To turn it into the **Tutor UI** referred to in [`docs/architecture.md`](../docs/architecture.md), future work should add:

1. A code-editor pane on the section view, posting student code to a local sandbox endpoint.
2. A hint/feedback pane that streams responses from a local LLM adapter (Ollama / llama.cpp / LM Studio).
3. A learner-state read/write layer talking to a small local store.

Keeping the frontend static means it can be hosted next to the backend as a `file://`-equivalent app, embedded in a desktop shell, or served by the tutor process itself.

## Provenance and license

- Frontend HTML/CSS/JS, PWA assets, and `content/sections.json` were copied and lightly adapted from [Python Power User](https://github.com/StewAlexander-com/Python-Power-User) (MIT, © Stew Alexander). The upstream repository is **not** modified by this project — it is used as a source only.
- Branding, copy, manifest metadata, service-worker cache key, and the 404 SPA-redirect base path were changed to fit this repository.
