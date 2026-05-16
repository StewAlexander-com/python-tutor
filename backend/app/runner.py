"""Prototype-grade Python code runner.

This module runs untrusted student code in a subprocess with:

* a hard wall-clock timeout (``TUTOR_RUN_TIMEOUT``, default 5s),
* an empty environment (no inherited PYTHONPATH, no user env, no
  caller secrets — see :func:`_safe_env`),
* ``-I`` isolated mode (ignore PYTHON* env vars, no user site-packages),
* a per-call temporary working directory created with permission 0o700
  and removed afterwards,
* size-limited captured stdout/stderr,
* a size cap on the code itself,
* a static AST scan via :mod:`app.safety` that blocks obvious hostile
  patterns (subprocess, networking, ``os.system``, raw ``open``, …)
  before execution, and
* on Unix, POSIX ``setrlimit`` calls in a ``preexec_fn`` to cap CPU,
  address space, file size, and the number of child processes.

This is *prototype safety*, not production sandboxing. Real isolation
(containers, microVMs, seccomp, network namespaces, cgroups) is out of
scope here and documented in ``docs/safety-and-sandboxing.md``. The
runner exists so the tutor can act on runtime evidence — never to host
adversarial workloads.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .safety import SafetyEvent, SafetyReport, analyze


# Hard ceilings. Configurable via env for local tweaking, but the upper
# bound is fixed so a misconfigured deploy can't grant generous limits.
def _bounded_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _bounded_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(lo, min(hi, value))


DEFAULT_TIMEOUT_SEC = _bounded_float("TUTOR_RUN_TIMEOUT", 5.0, 0.5, 30.0)
MAX_CODE_BYTES = _bounded_int("TUTOR_RUN_MAX_CODE_BYTES", 50_000, 1_000, 200_000)
MAX_OUTPUT_BYTES = _bounded_int("TUTOR_RUN_MAX_OUTPUT_BYTES", 32_000, 1_000, 200_000)

# Resource limits, only applied on POSIX where ``resource`` is available.
# CPU is wall-clock-independent — keep it close to the wall timeout so a
# hot loop doesn't burn through all of it. Memory is address space (RLIMIT_AS).
RUN_CPU_SECONDS = _bounded_int("TUTOR_RUN_CPU_SECONDS", 5, 1, 60)
RUN_MEM_MB = _bounded_int("TUTOR_RUN_MEM_MB", 256, 32, 4096)
RUN_FSIZE_MB = _bounded_int("TUTOR_RUN_FSIZE_MB", 16, 1, 256)
RUN_NPROC = _bounded_int("TUTOR_RUN_NPROC", 64, 8, 1024)

# When set to "1", the safety scanner also blocks WARN_MODULES (os,
# pathlib, shutil, tempfile, glob, importlib).
STRICT_IMPORTS = os.getenv("TUTOR_STRICT_IMPORTS", "0") == "1"


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool
    truncated: bool
    blocked: bool = False
    safety_events: list[dict] = field(default_factory=list)


class RunnerError(ValueError):
    """Raised for caller-visible runner problems (e.g. code too large)."""


def _truncate(data: bytes, limit: int) -> tuple[str, bool]:
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace"), False
    return (
        data[:limit].decode("utf-8", errors="replace")
        + f"\n... [truncated at {limit} bytes]",
        True,
    )


def _safe_env() -> dict[str, str]:
    """Minimal, deliberate environment for the student subprocess.

    Nothing from the caller's environment is inherited. We do NOT pass
    PATH — the runner invokes the interpreter by absolute path. Without
    PATH, code that tries ``os.system('curl ...')`` cannot find the
    binary even if it slipped past the static scanner.
    """
    return {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
        # Empty HOME prevents user-site lookups; -I already disables
        # user site, but a redundant guard is cheap.
        "HOME": "/nonexistent",
    }


def _preexec_limits():  # pragma: no cover - exercised only on POSIX
    """Return a preexec function that applies POSIX resource limits.

    Importing :mod:`resource` is deferred so this module still imports
    cleanly on platforms (notably Windows) that don't ship it. Returns
    ``None`` when ``resource`` is unavailable.
    """
    try:
        import resource  # type: ignore[import-not-found]
    except ImportError:
        return None

    def apply() -> None:
        # CPU seconds (RLIMIT_CPU): caps total CPU time the child can use.
        resource.setrlimit(
            resource.RLIMIT_CPU, (RUN_CPU_SECONDS, RUN_CPU_SECONDS)
        )
        # Address space (RLIMIT_AS): caps total virtual memory.
        mem = RUN_MEM_MB * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except (ValueError, OSError):
            # Some platforms (e.g. macOS) do not honour RLIMIT_AS for
            # Python. We accept that loss silently — wall-clock timeout
            # is still in force.
            pass
        # File size (RLIMIT_FSIZE): prevents filling the tempdir.
        fsize = RUN_FSIZE_MB * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        except (ValueError, OSError):
            pass
        # Core files: disabled.
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass
        # Process / thread count.
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (RUN_NPROC, RUN_NPROC))
        except (ValueError, AttributeError, OSError):
            pass

    return apply


def _events_to_payload(events: list[SafetyEvent]) -> list[dict]:
    return [asdict(e) for e in events]


def _blocked_result(report: SafetyReport) -> RunResult:
    detail = report.summary or "code blocked by safety policy"
    stderr = f"[safety] execution blocked: {detail}\n"
    return RunResult(
        stdout="",
        stderr=stderr,
        exit_code=-1,
        duration_ms=0,
        timed_out=False,
        truncated=False,
        blocked=True,
        safety_events=_events_to_payload(report.events),
    )


async def run_python(
    code: str,
    *,
    stdin: str = "",
    timeout: Optional[float] = None,
    python_executable: Optional[str] = None,
    skip_safety: bool = False,
) -> RunResult:
    """Execute *code* in an isolated Python subprocess and return its result.

    The function never raises on student-side failures (syntax errors,
    timeouts, non-zero exits, large output, blocked imports): all of
    those are returned in the :class:`RunResult`. It only raises
    :class:`RunnerError` for caller mistakes such as oversized code
    submissions.

    ``skip_safety=True`` bypasses the static AST scan. It exists for
    internal callers that have already validated the code (the exercise
    runner does its own checks on hidden test code); never expose it
    over the network.
    """
    if not isinstance(code, str):  # defensive — schema layer should catch this
        raise RunnerError("code must be a string")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise RunnerError(
            f"code exceeds {MAX_CODE_BYTES} bytes; refusing to run"
        )

    safety_events: list[SafetyEvent] = []
    if not skip_safety:
        report = analyze(code)
        if report.blocked:
            return _blocked_result(report)
        safety_events = report.events

    effective_timeout = (
        DEFAULT_TIMEOUT_SEC
        if timeout is None
        else max(0.5, min(30.0, float(timeout)))
    )
    py = python_executable or sys.executable

    workdir = Path(tempfile.mkdtemp(prefix="tutor-run-"))
    try:
        try:
            os.chmod(workdir, 0o700)
        except OSError:
            pass
        script = workdir / "main.py"
        script.write_text(code, encoding="utf-8")

        loop = asyncio.get_event_loop()
        start = loop.time()

        kwargs: dict = dict(
            cwd=str(workdir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_safe_env(),
        )
        preexec = _preexec_limits()
        if preexec is not None and os.name == "posix":
            kwargs["preexec_fn"] = preexec
            kwargs["start_new_session"] = True

        proc = await asyncio.create_subprocess_exec(
            py,
            "-I",  # isolated: ignore PYTHON* env vars and user site
            "-B",  # don't write .pyc files
            str(script),
            **kwargs,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin.encode("utf-8") if stdin else b""),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            # Kill the whole process group when we started one, so any
            # children the student spawned die with the parent.
            try:
                if kwargs.get("start_new_session"):
                    os.killpg(proc.pid, 9)
                else:
                    proc.kill()
            except (ProcessLookupError, PermissionError):
                pass
            stdout_bytes, stderr_bytes = await proc.communicate()

        duration_ms = int((loop.time() - start) * 1000)
        stdout, t1 = _truncate(stdout_bytes or b"", MAX_OUTPUT_BYTES)
        stderr, t2 = _truncate(stderr_bytes or b"", MAX_OUTPUT_BYTES)

        if timed_out and not stderr.endswith("\n"):
            stderr = (stderr + "\n" if stderr else "") + (
                f"[runner] killed after {effective_timeout:.1f}s timeout"
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        return RunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=t1 or t2,
            blocked=False,
            safety_events=_events_to_payload(safety_events),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
