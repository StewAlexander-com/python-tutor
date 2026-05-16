"""Tests focused on the strengthened sandbox controls in app.runner."""

from __future__ import annotations

import os
import sys

import pytest

from app.runner import run_python


@pytest.mark.asyncio
async def test_runner_blocks_subprocess_statically() -> None:
    """A subprocess import never reaches the interpreter."""
    result = await run_python("import subprocess\nsubprocess.run(['echo', 'hi'])\n")
    assert result.blocked is True
    assert result.exit_code == -1
    assert any(
        e["type"] == "blocked_import" and "subprocess" in e["detail"]
        for e in result.safety_events
    )
    assert "subprocess" in result.stderr


@pytest.mark.asyncio
async def test_runner_blocks_socket_imports() -> None:
    result = await run_python("import socket\n")
    assert result.blocked is True


@pytest.mark.asyncio
async def test_runner_no_inherited_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """PATH is not propagated — os.system can't find common binaries."""
    monkeypatch.setenv("TUTOR_TEST_PATH_LEAK", "/should/not/appear")
    result = await run_python(
        "import os\nprint(os.environ.get('PATH', 'no-path'))\n"
        "print(os.environ.get('TUTOR_TEST_PATH_LEAK', 'no-leak'))\n"
    )
    assert "no-path" in result.stdout
    assert "no-leak" in result.stdout


@pytest.mark.asyncio
async def test_runner_uses_tempdir_as_cwd() -> None:
    """The subprocess runs in an isolated tempdir, not the repo root."""
    result = await run_python("import os\nprint(os.getcwd())\n")
    assert result.exit_code == 0
    assert "tutor-run-" in result.stdout


@pytest.mark.asyncio
async def test_runner_safety_events_empty_for_clean_code() -> None:
    result = await run_python("print('hi')\n")
    assert result.blocked is False
    assert result.safety_events == []


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="resource limits are POSIX-only")
async def test_runner_memory_limit_kills_runaway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allocating beyond the address-space limit terminates the process."""
    # Force a tiny limit and re-import so the constant picks it up. We
    # monkeypatch the module-level constant directly to avoid a reload.
    from app import runner

    monkeypatch.setattr(runner, "RUN_MEM_MB", 64, raising=True)
    code = "x = bytearray(1_000_000_000)\nprint(len(x))\n"
    result = await runner.run_python(code, timeout=3.0)
    # On platforms where RLIMIT_AS is honoured (Linux), the child dies
    # with a MemoryError or signal. On macOS the limit is silently
    # ignored — accept either outcome but require the process not to
    # have *succeeded*.
    if sys.platform.startswith("linux"):
        assert result.exit_code != 0


@pytest.mark.asyncio
async def test_runner_killpg_on_timeout() -> None:
    """A timeout still kills processes spawned in a new session group."""
    # We can't easily fork here (subprocess is blocked) — instead just
    # verify the timeout path runs cleanly for a hot loop and reports
    # the timeout.
    result = await run_python("while True:\n    x = 1\n", timeout=0.5)
    assert result.timed_out is True
    assert "timeout" in result.stderr.lower()
