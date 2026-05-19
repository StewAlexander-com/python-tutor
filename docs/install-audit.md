# Install audit & reliability runbook

This document captures real-world install failure modes observed in the
wild and the script-level mitigations that ship in `install.sh` /
`run.sh`. Treat it as the runbook a fresh contributor reaches for when
something goes sideways on a new host.

## Origins

The audit was triggered by a real install on a macOS laptop that
exposed several gaps in the earlier scripts:

- Python 3.14 was present, but the semver parser in `install.sh`
  incorrectly extracted the patch component as "minor". It worked by
  luck on `3.14.4`; it would have rejected `3.10.0` / `3.11.0` outright.
- `gh auth` had an invalid token, so a direct `gh repo clone` of a
  private mirror failed. The error was clear but the README did not
  acknowledge it.
- `pip install` failed because DNS could not resolve `pypi.org`.
  The script printed raw pip output and exited; no hint about offline
  wheelhouses, proxies, or internal mirrors.
- Ollama was installed but the daemon was not running. The probe
  worked, but the recovery path required the user to know the magic
  `ollama serve` invocation.
- The remote command sandbox could not talk to `localhost:11434`
  directly; only an interactive Terminal session could. Nothing in the
  scripts surfaced this distinction.
- After verification the install was moved to `~/Projects/python-tutor`.
  The venv had to be rebuilt because virtualenvs hard-code their own
  path inside `pyvenv.cfg` and the shebangs of `bin/*`.

## What changed

### `install.sh`

| Change | Why |
| --- | --- |
| Proper semver parser using `sys.version_info[:2]` | The old `${ver##*.}` pattern silently misparsed 3-component versions like `3.10.0`. |
| Preflight report at the top | Lets the user see OS, Python, Ollama state, model, and mode in one screen before anything mutates the host. |
| Venv path-sensitivity marker (`.tutor_repo_root`) | Rebuilds the venv automatically if the repo was moved since the last install, so users do not get cryptic shebang failures. |
| Captured pip output + DNS/proxy hint detection | When pip fails, the script greps for known network signatures (`name or service not known`, `getaddrinfo`, etc.) and prints the offline wheelhouse recipe. |
| `--help`, `--yes`, `--noninteractive`, `--no-launch`, `--skip-ollama`, `--skip-model-pull`, `--model TAG` flags | Old env-var-only interface was inscrutable. Flags are sugar over the same env vars; existing scripts keep working. |
| Documented exit codes (0/1/2/3) | Lets CI and parent scripts distinguish "Python missing" from "pip failed" from "bad CLI". |

### `run.sh`

| Change | Why |
| --- | --- |
| `--help`, `--host`, `--port`, `--model`, `--open-browser`, `--no-launch`, `--skip-ollama`, `-y`, `-n` | Same rationale as install.sh: discoverability. |
| Port-in-use probe via `/dev/tcp` before exec'ing uvicorn | uvicorn's bind-error is ugly; the script now exits 4 with `pick another port`. No new system deps required (no `lsof`/`ss`). |
| `--open-browser` background watcher | Polls `/api/health` and opens the URL only after the server reports healthy, so the browser does not race the bind. |
| `--no-launch` | Lets CI exercise the full preflight (venv check, Ollama probe, port-in-use) without binding a socket. |
| Documented exit codes (0/3/4) | Same reason as install.sh. |

## Failure modes & remediations

### "Python 3.10+ is required and was not found on PATH"

The script iterates `python3.13 python3.12 python3.11 python3.10 python3`
and accepts the first interpreter whose `sys.version_info[:2]` is
`>= (3, 10)`. If you have a newer Python under a non-default name
(e.g. `python3.14` via `pyenv`), make sure it is on `PATH` or symlink
it as `python3.13`.

### `pip install` fails on a network you don't control

The script now prints actionable hints whenever pip's log contains a
known network signature. Three paths:

1. **Behind a corporate proxy:**

   ```bash
   export HTTPS_PROXY=http://proxy.example:8080
   export HTTP_PROXY=http://proxy.example:8080
   ./install.sh
   ```

2. **Internal mirror:**

   ```bash
   PIP_INDEX_URL=https://pypi.internal/simple ./install.sh
   ```

3. **Fully offline / air-gapped:** build a wheelhouse on a connected
   host, copy it over, then install from disk only.

   ```bash
   # On a host with pypi access:
   pip download -d wheelhouse -r backend/requirements-dev.txt
   # scp/rsync wheelhouse/ to the target host, then:
   PIP_NO_INDEX=1 PIP_FIND_LINKS="$PWD/wheelhouse" ./install.sh
   ```

### "venv at backend/.venv looks broken"

Almost always means the repo was moved (or copied) after the venv was
created. The script detects this via the `.tutor_repo_root` marker and
rebuilds. If you intentionally moved the repo and want to keep the venv,
the only safe move is to recreate it -- there is no supported way to
relocate a virtualenv.

### "Port 8001 is already in use"

`run.sh --port 8002` (or any free port). The port-in-use probe uses
bash's `/dev/tcp` so it works without `lsof` / `ss` / `netstat`.

### "Ollama is installed but the daemon is not running on :11434"

Two paths:

1. Let the script start it: answer `y` to "Start 'ollama serve' in the
   background now?" -- the daemon log goes to `/tmp/ollama-serve.log`.
2. Start it yourself in another Terminal: `ollama serve`. Some hosts
   (notably remote command sandboxes) cannot reach `localhost:11434`
   from a non-interactive session even when the daemon is running --
   in that case, run `./install.sh` from an interactive Terminal.

### `gh repo clone` fails with an auth error on a private repo

```bash
gh auth status         # check current token
gh auth refresh        # re-authorize
gh auth login          # full re-login (web flow)
```

The public mirror at `https://github.com/StewAlexander-com/python-tutor`
does not require auth; only private forks do.

## Recommended install / run commands

Interactive (default):

```bash
gh repo clone StewAlexander-com/python-tutor
cd python-tutor
./install.sh        # prompts y/N for any host-level change
./run.sh            # serves UI + API at http://localhost:8001/
```

Unattended (trusted host -- installs Ollama, pulls model, launches):

```bash
./install.sh --yes
```

CI / dry-run (no system changes, no server):

```bash
./install.sh --noninteractive --skip-ollama --skip-model-pull --no-launch
./run.sh --no-launch --skip-ollama
```

Custom port with a browser pop:

```bash
./run.sh --port 8042 --open-browser
```
