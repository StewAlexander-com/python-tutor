# Walkthrough screenshots

These images are linked from the project [README](../../../README.md) to give
visitors a quick visual tour of the Python Tutor.

| File                         | What it shows                                                  |
| ---------------------------- | -------------------------------------------------------------- |
| `01-home.png`                | Landing page — two learning paths and the "Ask tutor" FAB.     |
| `02-lesson-browser.png`      | The 46-section beginner browser with search.                   |
| `03-section-view.png`        | A lesson opened in the **Teaching** reading mode.              |
| `04-code-lab-run.png`        | The inline code lab after pressing **Run** (stdout panel).     |
| `05-evaluate-feedback.png`   | Tutor evaluation: assessment, feedback, next step, references. |
| `06-tutor-chat.png`          | Floating chat panel mid-conversation.                          |

## How they're generated

The shots are captured by [`scripts/capture-screenshots.js`](../../../scripts/capture-screenshots.js)
using Playwright. The script serves `frontend/` on a local port and **mocks**
`/api/health`, `/api/run`, `/api/evaluate`, and `/api/chat` so the UI renders
its happy-path states without requiring Ollama to be installed or running.

The mocked model responses are **deterministic fixtures** chosen to illustrate
the UI — they are *not* real Gemma output. If you want screenshots of real
model output, start the backend (`./run.sh`) and capture them manually.

To regenerate:

```bash
npm i --no-save playwright
npx playwright install chromium
node scripts/capture-screenshots.js
```
