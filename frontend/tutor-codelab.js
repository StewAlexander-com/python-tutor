/* =========================================================
   tutor-codelab.js — Offline Python Tutor
   Inline code-lab pane for the lesson view. Mounted by app.js
   after a section finishes rendering. Provides:

     - A monospace <textarea> editor seeded from the section's
       first demo code block (when one exists).
     - "Run" → POST /api/run, shows stdout / stderr / exit code,
       duration, timeout flag.
     - "Evaluate" → POST /api/evaluate with code + last run +
       section title + optional question. Shows assessment,
       feedback (markdown-ish), and a next-step suggestion.
     - Open in chat → forwards the current code & last run into
       the floating tutor-chat panel so free-form follow-up keeps
       full context.

   Design language reuses the chat panel tokens (amber accent on
   dark surfaces, mono labels). No new colours.

   Safety surface: a small "prototype safety" note is always
   visible next to Run.
   ========================================================= */

(() => {
  'use strict';

  function resolveBackend() {
    if (typeof window.TUTOR_BACKEND_URL === 'string') return window.TUTOR_BACKEND_URL;
    const meta = document.querySelector('meta[name="tutor-backend"]');
    if (meta && meta.content) return meta.content.trim();
    try {
      const stored = localStorage.getItem('tutor-backend');
      if (stored) return stored;
    } catch (_) { /* ignore */ }
    const { protocol, hostname, port } = location;
    if (port && port !== '8001' && (hostname === 'localhost' || hostname === '127.0.0.1')) {
      return `${protocol}//${hostname}:8001`;
    }
    return '';
  }

  const BACKEND = resolveBackend();
  const api = (path) => (BACKEND ? BACKEND.replace(/\/$/, '') : '') + path;

  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);

  // Same minimal markdown renderer the chat module uses, kept local so this
  // file works even if tutor-chat.js has not loaded yet.
  function renderMarkdownish(text) {
    const src = String(text || '');
    const parts = [];
    let i = 0;
    while (i < src.length) {
      const fenceStart = src.indexOf('```', i);
      if (fenceStart === -1) { parts.push({ type: 'text', value: src.slice(i) }); break; }
      if (fenceStart > i) parts.push({ type: 'text', value: src.slice(i, fenceStart) });
      const fenceEnd = src.indexOf('```', fenceStart + 3);
      if (fenceEnd === -1) {
        parts.push({ type: 'code', value: src.slice(fenceStart + 3) });
        break;
      }
      const inner = src.slice(fenceStart + 3, fenceEnd);
      const nl = inner.indexOf('\n');
      const code = nl === -1 ? inner : inner.slice(nl + 1);
      parts.push({ type: 'code', value: code });
      i = fenceEnd + 3;
    }
    return parts.map((p) => {
      if (p.type === 'code') {
        return `<pre class="codelab__code"><code>${escapeHtml(p.value.replace(/\n$/, ''))}</code></pre>`;
      }
      const escaped = escapeHtml(p.value).replace(/`([^`\n]+)`/g, '<code class="codelab__icode">$1</code>');
      return escaped.split(/\n{2,}/).map((para) => `<p>${para.replace(/\n/g, '<br>')}</p>`).join('');
    }).join('');
  }

  // Extract a starter snippet from a section. The renderer puts the demo's
  // code into <pre><code> blocks within #secBody. We pick the first one as
  // a seed; if none, fall back to a one-liner.
  function pickStarterCode(secEl) {
    if (!secEl) return 'print("hello, tutor")\n';
    const pre = secEl.querySelector('pre code');
    if (pre && pre.textContent && pre.textContent.trim().length) {
      return pre.textContent.replace(/ /g, ' ');
    }
    return 'print("hello, tutor")\n';
  }

  function sectionLabel(sec) {
    if (!sec) return null;
    const num = sec.number != null ? `Section ${String(sec.number).padStart(2, '0')}` : '';
    const title = sec.title || '';
    if (num && title) return `${num} — ${title}`;
    return title || num || null;
  }

  function renderRun(runResp) {
    if (!runResp) return '';
    const status = runResp.timed_out
      ? 'timeout'
      : (runResp.exit_code === 0 ? 'ok' : 'error');
    const dot = `<span class="codelab__dot codelab__dot--${status}" aria-hidden="true"></span>`;
    const label = status === 'ok' ? 'Ran cleanly' : (status === 'timeout' ? 'Timed out' : `Exit ${runResp.exit_code}`);
    const meta = `<span class="codelab__meta">${escapeHtml(label)} · ${runResp.duration_ms} ms${runResp.truncated ? ' · output truncated' : ''}</span>`;
    const stdout = runResp.stdout
      ? `<details class="codelab__io" open><summary>stdout</summary><pre class="codelab__pre">${escapeHtml(runResp.stdout)}</pre></details>`
      : '';
    const stderr = runResp.stderr
      ? `<details class="codelab__io codelab__io--err" open><summary>stderr</summary><pre class="codelab__pre">${escapeHtml(runResp.stderr)}</pre></details>`
      : '';
    return `<div class="codelab__runline">${dot}${meta}</div>${stdout}${stderr}`;
  }

  function renderEvaluation(evalResp) {
    if (!evalResp) return '';
    const verdict = (evalResp.assessment || 'needs_work').replace('_', ' ');
    const cls = `codelab__verdict codelab__verdict--${evalResp.assessment || 'needs_work'}`;
    const next = evalResp.next_step
      ? `<p class="codelab__next"><strong>Next step:</strong> ${escapeHtml(evalResp.next_step)}</p>`
      : '';
    return `
      <article class="codelab__feedback" aria-live="polite">
        <header class="codelab__verdict-row">
          <span class="${cls}">${escapeHtml(verdict)}</span>
          <span class="codelab__model">via ${escapeHtml(evalResp.model || '')}</span>
        </header>
        <div class="codelab__body">${renderMarkdownish(evalResp.feedback || '')}</div>
        ${next}
      </article>`;
  }

  function buildLabHtml() {
    return `
      <section class="codelab" aria-labelledby="codelabTitle">
        <header class="codelab__head">
          <h2 class="codelab__title" id="codelabTitle">Try it</h2>
          <p class="codelab__sub">
            Edit the snippet, press <strong>Run</strong> to see what Python
            actually does, then <strong>Evaluate</strong> to ask the tutor.
          </p>
        </header>

        <label class="codelab__field">
          <span class="codelab__label">Your code</span>
          <textarea class="codelab__editor" id="codelabEditor" spellcheck="false"
                    autocapitalize="off" autocorrect="off" rows="10"></textarea>
        </label>

        <label class="codelab__field codelab__field--q">
          <span class="codelab__label">Optional question for the tutor</span>
          <input class="codelab__q" id="codelabQuestion" type="text"
                 placeholder="e.g. why is the output off by one?" />
        </label>

        <div class="codelab__bar">
          <button type="button" class="codelab__btn codelab__btn--ghost" id="codelabReset" aria-label="Reset to original snippet">Reset</button>
          <span class="codelab__safety" title="Prototype safety only — subprocess + timeout + restricted env, not a real sandbox">
            prototype safety · subprocess + timeout
          </span>
          <span class="codelab__spacer"></span>
          <button type="button" class="codelab__btn" id="codelabRun">Run</button>
          <button type="button" class="codelab__btn codelab__btn--primary" id="codelabEval">Evaluate</button>
        </div>

        <div class="codelab__results" id="codelabResults"></div>
      </section>
    `;
  }

  async function postJson(path, body) {
    const res = await fetch(api(path), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* may be empty */ }
    if (!res.ok) {
      const detail = data && data.detail ? data.detail : res.statusText;
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    return data;
  }

  function mountInto(container, sec) {
    if (!container) return;
    // Don't mount twice if app.js re-renders the same section.
    container.querySelectorAll('.codelab').forEach((n) => n.remove());

    const wrap = document.createElement('div');
    wrap.innerHTML = buildLabHtml();
    const lab = wrap.firstElementChild;
    container.appendChild(lab);

    const editor = lab.querySelector('#codelabEditor');
    const qEl = lab.querySelector('#codelabQuestion');
    const runBtn = lab.querySelector('#codelabRun');
    const evalBtn = lab.querySelector('#codelabEval');
    const resetBtn = lab.querySelector('#codelabReset');
    const results = lab.querySelector('#codelabResults');

    const starter = pickStarterCode(container);
    editor.value = starter;

    const section = sectionLabel(sec);
    const state = { lastRun: null, busy: false };

    function setBusy(which) {
      state.busy = !!which;
      runBtn.disabled = state.busy;
      evalBtn.disabled = state.busy;
      if (which === 'run') runBtn.textContent = 'Running…';
      else if (which === 'evaluate') evalBtn.textContent = 'Evaluating…';
      else {
        runBtn.textContent = 'Run';
        evalBtn.textContent = 'Evaluate';
      }
    }

    function renderResults({ run, evaluation, error } = {}) {
      const parts = [];
      if (error) {
        parts.push(`<div class="codelab__error" role="alert">${escapeHtml(error)}</div>`);
      }
      if (run) parts.push(renderRun(run));
      if (evaluation) parts.push(renderEvaluation(evaluation));
      results.innerHTML = parts.join('');
    }

    runBtn.addEventListener('click', async () => {
      if (state.busy) return;
      setBusy('run');
      try {
        const data = await postJson('/api/run', { code: editor.value });
        state.lastRun = data;
        renderResults({ run: data });
      } catch (err) {
        renderResults({ error: `Run failed — ${err.message}` });
      } finally {
        setBusy(false);
      }
    });

    evalBtn.addEventListener('click', async () => {
      if (state.busy) return;
      setBusy('evaluate');
      try {
        const payload = {
          code: editor.value,
          section: section || undefined,
          question: (qEl.value || '').trim() || undefined,
          run_output: state.lastRun || undefined,
        };
        const data = await postJson('/api/evaluate', payload);
        state.lastRun = data.run;
        renderResults({ run: data.run, evaluation: data });
      } catch (err) {
        renderResults({ run: state.lastRun, error: `Evaluate failed — ${err.message}` });
      } finally {
        setBusy(false);
      }
    });

    resetBtn.addEventListener('click', () => {
      editor.value = starter;
      state.lastRun = null;
      results.innerHTML = '';
    });

    // Cmd/Ctrl+Enter runs the code from inside the editor.
    editor.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        runBtn.click();
      }
    });
  }

  window.TutorCodeLab = { mountInto, get backend() { return BACKEND; } };
})();
