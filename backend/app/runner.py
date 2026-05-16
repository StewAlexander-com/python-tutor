"""Prototype-grade Python code runner.

This module runs untrusted student code in a subprocess with:

* a hard wall-clock timeout (`TUTOR_RUN_TIMEOUT`, default 5s),
* an empty environment (no inherited PYTHONPATH, no user env),
* `-I` isolated mode (ignore PYTHON* env vars, no user site-packages),
* a temporary working directory created per call and removed afterwards,
* size-limited captured stdout/stderr,
* an optional size cap on the code itself.

This is *prototype safety*, not production sandboxing. Real isolation
(containers, microVMs, seccomp, network namespaces) is out of scope here
and documented in docs/safety-and-sandboxing.md. The runner exists so the
tutor can act on runtime evidence — never to host adversarial workloads.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool
    truncated: bool


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


async def run_python(
    code: str,
    *,
    stdin: str = "",
    timeout: Optional[float] = None,
    python_executable: Optional[str] = None,
) -> RunResult:
    """Execute *code* in an isolated Python subprocess and return its result.

    The function never raises on student-side failures (syntax errors,
    timeouts, non-zero exits, large output): all of those are returned in
    the `RunResult`. It only raises `RunnerError` for caller mistakes such
    as oversized code submissions.
    """
    if not isinstance(code, str):  # defensive — schema layer should catch this
        raise RunnerError("code must be a string")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise RunnerError(
            f"code exceeds {MAX_CODE_BYTES} bytes; refusing to run"
        )

    effective_timeout = (
        DEFAULT_TIMEOUT_SEC
        if timeout is None
        else max(0.5, min(30.0, float(timeout)))
    )
    py = python_executable or sys.executable

    workdir = Path(tempfile.mkdtemp(prefix="tutor-run-"))
    try:
        script = workdir / "main.py"
        script.write_text(code, encoding="utf-8")

        loop = asyncio.get_event_loop()
        start = loop.time()

        proc = await asyncio.create_subprocess_exec(
            py,
            "-I",  # isolated: ignore PYTHON* env vars and user site
            "-B",  # don't write .pyc files
            str(script),
            cwd=str(workdir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                # Minimal, deliberate env. No PATH manipulation, no LANG
                # carry-over. PYTHONIOENCODING keeps stdout decodable.
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "LC_ALL": "C.UTF-8",
            },
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin.encode("utf-8") if stdin else b""),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except ProcessLookupError:
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
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
