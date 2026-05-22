# Python Tutor

**A private, offline Python tutor that runs entirely on your own machine.**

Lessons, an interactive code lab, and an AI mentor — powered by a local LLM
(Gemma via Ollama). No accounts, no cloud, no telemetry. Open a browser, learn
Python, write code, get feedback. Your code and your questions never leave the
laptop.

> **Start here:** <https://stewalexander-com.github.io/python-tutor/> — the
> project's GitHub Pages start page with the three-command install and a
> 30-second visual tour. Source for the page lives in [`site/`](site/).

```
┌─────────────────────────────────────────────────────────┐
│  Read a lesson  →  Run code in the lab  →  Ask tutor    │
│                       (all local, all offline)          │
└─────────────────────────────────────────────────────────┘
```

---

## Why it exists

| For…                       | It gives you                                                |
| -------------------------- | ----------------------------------------------------------- |
| **Self-learners**          | A guided Python curriculum with a chat tutor on demand.     |
| **Educators**              | A drop-in lab where students run code and get evidence-based hints. |
| **Privacy-minded teams**   | A tutor that works on an air-gapped laptop — nothing phones home. |
| **Tinkerers**              | A clean FastAPI + static-PWA stack to remix and extend.     |

---

## What you get

| Feature                       | What it does                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------- |
| 🧠 **Local LLM tutor**        | Chat with a model running on your machine (default: `gemma3:4b` via Ollama). |
| 📓 **Lesson library**         | A PWA you can install, with a Python-foundations curriculum.                 |
| 🧪 **Inline code lab**        | Edit → **Run** → **Evaluate**. The tutor sees the real output, not a guess.  |
| ✅ **Graded exercises**        | Visible + hidden test cases, per-assertion pass/fail.                        |
| 📚 **Official docs links**    | Answers cite `docs.python.org` and friends from a curated allowlist — no hallucinated URLs. |
| 🛡 **Prototype-grade safety** | Static AST scan, isolated subprocess, timeouts, rlimits, scrubbed env.       |
| 🔌 **Works offline**          | UI runs without the LLM; only chat/evaluate need Ollama up.                  |

---

## Project website / start page

The project's **start page** is published on GitHub Pages:

**<https://stewalexander-com.github.io/python-tutor/>**

It's the link to share with anyone who hasn't cloned the repo yet: dark /
amber aesthetic, the local-first loop in four steps, the three-command
install with copy buttons, and links to the repo, README, and issues.

Source lives in [`site/`](site/) and is deployed by
[`.github/workflows/pages.yml`](.github/workflows/pages.yml) on every push
to `main` that touches `site/`. The Pages workflow runs independently of
the regular CI workflow.

To preview locally (pure static HTML + CSS, no build step):

```bash
cd site
python3 -m http.server 8080
# open http://localhost:8080/
```

See [`site/README.md`](site/README.md) for what's in it and the asset layout.

---

## A quick look

A 30-second tour of the UI, lab, and tutor. Click any image to enlarge.

<table>
  <tr>
    <td width="50%" align="center">
      <a href="docs/assets/screenshots/01-home.png">
        <img src="docs/assets/screenshots/01-home.png" alt="Landing page with two learning paths: 'I'm new to Python' and 'I need a quick reference'." />
      </a>
      <sub><b>Land.</b> Two paths — beginner or quick reference. The "Ask tutor" button is always one tap away.</sub>
    </td>
    <td width="50%" align="center">
      <a href="docs/assets/screenshots/02-lesson-browser.png">
        <img src="docs/assets/screenshots/02-lesson-browser.png" alt="Beginner-path browser showing 46 sections starting with Variables &amp; Types, Numbers &amp; Math, Strings." />
      </a>
      <sub><b>Browse.</b> 46 sections, filterable, grouped by theme. Read in order or jump straight to a topic.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <a href="docs/assets/screenshots/03-section-view.png">
        <img src="docs/assets/screenshots/03-section-view.png" alt="Variables &amp; Types lesson in Teaching mode, opened to the 'Big picture' explainer." />
      </a>
      <sub><b>Read.</b> Each section explains the <i>why</i> first, then the syntax. Switch between Teaching and Quick reference modes.</sub>
    </td>
    <td width="50%" align="center">
      <a href="docs/assets/screenshots/04-code-lab-run.png">
        <img src="docs/assets/screenshots/04-code-lab-run.png" alt="Inline code lab with a small Python program, the Run button, and a green 'Ran cleanly' stdout panel." />
      </a>
      <sub><b>Run.</b> Edit the snippet, press <b>Run</b>, see real stdout/stderr and exit code — actually executed, not faked.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <a href="docs/assets/screenshots/05-evaluate-feedback.png">
        <img src="docs/assets/screenshots/05-evaluate-feedback.png" alt="Tutor evaluation: 'On track' verdict, prose feedback, a Next step, and official Python docs references." />
      </a>
      <sub><b>Evaluate.</b> The tutor sees your code <i>and</i> what it actually printed, gives a verdict, a next step, and links to official docs.</sub>
    </td>
    <td width="50%" align="center">
      <a href="docs/assets/screenshots/06-tutor-chat.png">
        <img src="docs/assets/screenshots/06-tutor-chat.png" alt="Floating chat panel mid-conversation about why Python variables are not typed, with a small code example in the reply." />
      </a>
      <sub><b>Ask.</b> A floating chat panel for free-form questions — your code and lesson context come along for the ride.</sub>
    </td>
  </tr>
</table>

> The screenshots above are produced by
> [`scripts/capture-screenshots.js`](scripts/capture-screenshots.js) with
> deterministic UI fixtures so they stay reproducible without Ollama running.
> Real model output will read differently — for the look of the UI, they're
> faithful. See [`docs/assets/screenshots/README.md`](docs/assets/screenshots/README.md).

---

## How it works

```mermaid
flowchart LR
    Student((You)) -->|reads, edits, asks| UI[PWA frontend]
    UI -->|/api/run| Sandbox[Python sandbox<br/>subprocess + AST scan]
    UI -->|/api/evaluate| Evidence[Evidence packet<br/>code + output + docs]
    UI -->|/api/chat| Chat[Chat]
    Evidence --> LLM[Local LLM<br/>Ollama / Gemma]
    Chat --> LLM
    LLM --> UI
    Sandbox --> UI
```

The teaching loop:

```mermaid
flowchart LR
    A[Read lesson] --> B[Edit code]
    B --> C[Run]
    C --> D{Worked?}
    D -- yes --> E[Reflect / next lesson]
    D -- no --> F[Evaluate]
    F --> G[Hint-first feedback<br/>+ docs link]
    G --> B
```

The LLM teaches, explains, and guides. The **runtime** verifies — the tutor
never claims code works without running it.

---

## Quick start

Two commands. macOS or Linux. Python 3.10+.

```bash
gh repo clone StewAlexander-com/python-tutor
cd python-tutor
./install.sh        # sets up venv, then prompts y/N for any host-level step
./run.sh            # serves UI + API at http://localhost:8001/
```

Open <http://localhost:8001/> — you'll land on the lesson list with the code lab
and floating "Ask tutor" panel.

> `install.sh` only touches the repo on its own. **Installing Ollama, starting
> the daemon, pulling the model, or launching the app are all opt-in y/N
> prompts.** Press Enter and nothing changes on your host.

Run `./install.sh --help` or `./run.sh --help` for every option. The most
common shapes:

```bash
./install.sh --yes               # trusted host: install Ollama, pull model, launch
./install.sh --noninteractive    # CI: never prompt, default everything to "no"
./install.sh --skip-ollama       # set up Python only; skip every Ollama probe
./install.sh --model llama3.1:8b # use a different model than gemma3:4b
./run.sh --port 8042             # choose a different port
./run.sh --open-browser          # open the URL once /api/health is green
```

The classic env vars (`TUTOR_NONINTERACTIVE`, `PYTHON_TUTOR_ASSUME_YES`,
`TUTOR_SKIP_OLLAMA`, `TUTOR_MODEL`, `TUTOR_PORT`, …) still work — the flags
are sugar on top of them.

Full env-var list and design rationale:
[`docs/install-runtime-workflow.md`](docs/install-runtime-workflow.md).

---

## Install reliability

`install.sh` and `run.sh` are designed so the obvious failures fail
*loudly* with a concrete next step. The most common ones:

| Symptom                                       | What to do                                      |
| --------------------------------------------- | ----------------------------------------------- |
| "Python 3.10+ is required and was not found"  | `brew install python@3.12` / `apt install python3.12` and re-run. |
| `pip install` fails on DNS / proxy / pypi     | The script detects this and prints offline/proxy/wheelhouse recipes. See [install-audit.md](docs/install-audit.md#pip-install-fails-on-a-network-you-dont-control). |
| "Port 8001 is already in use"                 | `./run.sh --port 8002` (probe uses `/dev/tcp`, no `lsof` needed). |
| Ollama installed but daemon down on `:11434`  | Answer `y` to "Start `ollama serve` now?" or run it yourself in another Terminal. |
| `gh repo clone` fails with auth error         | `gh auth status` → `gh auth login`. Public clone via HTTPS also works. |
| Repo was moved after install -> "venv broken" | The script auto-rebuilds. Virtualenvs hard-code their own path; relocating is unsupported by Python itself. |

Detailed runbook and the audit that produced these mitigations:
[`docs/install-audit.md`](docs/install-audit.md).

---

## Architecture at a glance

```
┌──────────────────────────┐      ┌──────────────────────────┐
│  frontend/  (static PWA) │◀────▶│  backend/  (FastAPI)     │
│  lesson list • code lab  │      │  /api/run /api/evaluate  │
│  floating chat FAB       │      │  /api/chat /api/exercises│
└──────────────────────────┘      └──────────┬───────────────┘
                                             │
                                             ▼
                                  ┌──────────────────────────┐
                                  │  Ollama (local LLM)      │
                                  │  default: gemma3:4b      │
                                  └──────────────────────────┘
```

| Layer                | Where it lives                          | Read more                                  |
| -------------------- | --------------------------------------- | ------------------------------------------ |
| Frontend (PWA)       | [`frontend/`](frontend/)                | [`frontend/README.md`](frontend/README.md) |
| Backend (FastAPI)    | [`backend/`](backend/)                  | [`backend/README.md`](backend/README.md)   |
| Curriculum & exercises | [`curriculum/`](curriculum/)          | [`curriculum/exercises/README.md`](curriculum/exercises/README.md) |
| Sandbox & safety     | [`backend/app/safety.py`](backend/app/safety.py) | [`docs/safety-and-sandboxing.md`](docs/safety-and-sandboxing.md) |
| Architecture         | —                                       | [`docs/architecture.md`](docs/architecture.md) |
| UX workflow          | —                                       | [`docs/ux-workflow.md`](docs/ux-workflow.md) |

---

## A word on safety

The sandbox is **prototype safety, not production isolation**. It is stronger
than a bare `subprocess.run`, but a local single-user tutor is its design
target — not a multi-tenant code execution service.

| In force                                                | Not in force                          |
| ------------------------------------------------------- | ------------------------------------- |
| Static AST scan (rejects `subprocess`, `socket`, `ctypes`, `pickle`, `os.system`, `exec`, `eval`, `__import__`, …) | Kernel-level isolation                |
| Isolated `python -I -B` subprocess, scrubbed env        | Defense against side-channel attacks  |
| Per-call tempdir at `0o700`, removed after run          | macOS `RLIMIT_AS` (Python ignores it) |
| Wall-clock timeout + process-group kill                 | Windows POSIX rlimits                 |
| POSIX rlimits: CPU, memory, file size, nproc            |                                       |
| Output truncation + code-size cap                       |                                       |

For multi-tenant or hostile workloads, wrap the runner in a container, a
microVM, or a restricted user. Details and threat model:
[`docs/safety-and-sandboxing.md`](docs/safety-and-sandboxing.md).

---

## Documentation citations

The tutor only cites **official Python docs from a curated allowlist** —
`docs.python.org`, `peps.python.org`, `packaging.python.org`, plus the official
sites for NumPy, pandas, Matplotlib, SciPy, Flask, FastAPI, Django, Requests,
HTTPX, SQLAlchemy, pytest, and mypy. URLs are **never generated by the LLM**:
they come from an in-repo map ([`backend/app/docs_refs.py`](backend/app/docs_refs.py))
or exercise-supplied references. When online, each link is HEAD-checked before
display; unreachable links are dropped or flagged "unverified".

---

## CI

GitHub Actions runs on every push and pull request: backend tests, a static
safety scan over the curriculum, and a Markdown link sanity check. See
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Going deeper

- [Architecture](docs/architecture.md)
- [Workflow](docs/workflow.md)
- [UX workflow](docs/ux-workflow.md)
- [Safety & sandboxing](docs/safety-and-sandboxing.md)
- [Evaluation](docs/evaluation.md)
- [Roadmap](docs/roadmap.md)
- [Install & runtime workflow](docs/install-runtime-workflow.md)
- [Install reliability audit](docs/install-audit.md)
- [Python foundations curriculum](curriculum/python-foundations.md)
- [Tutor system prompt](prompts/tutor-system-prompt.md)
- [ADR 0001 — offline-first local LLM](adr/0001-offline-first-local-llm.md)

---

## Credits

The static PWA frontend was adapted from
[Python Power User](https://github.com/StewAlexander-com/Python-Power-User) (MIT).
