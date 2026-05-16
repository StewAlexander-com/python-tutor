"""Tests for the static safety scanner in app.safety."""

from __future__ import annotations

import os

import pytest

from app import safety
from app.safety import analyze


def test_clean_code_is_not_blocked() -> None:
    report = analyze("print(2 + 2)\nfor i in range(3):\n    pass\n")
    assert report.blocked is False
    assert report.events == []


def test_syntax_error_is_reported_but_not_blocked() -> None:
    report = analyze("def broken(:\n")
    assert report.blocked is False
    assert len(report.events) == 1
    assert report.events[0].type == "syntax_error"


@pytest.mark.parametrize(
    "code",
    [
        "import subprocess\n",
        "from subprocess import Popen\n",
        "import socket\n",
        "import ctypes\n",
        "import urllib.request\n",
        "import multiprocessing\n",
        "import pickle\n",
        "from http.client import HTTPConnection\n",
    ],
)
def test_blocks_hostile_imports(code: str) -> None:
    report = analyze(code)
    assert report.blocked is True
    assert any(e.type == "blocked_import" for e in report.events)


@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.system('echo hi')\n",
        "exec('print(1)')\n",
        "eval('1+1')\n",
        "__import__('subprocess')\n",
    ],
)
def test_blocks_dangerous_calls(code: str) -> None:
    report = analyze(code)
    assert report.blocked is True
    assert any(e.type == "blocked_call" for e in report.events)


def test_open_is_allowed_by_default() -> None:
    report = analyze("with open('hello.txt', 'w') as f:\n    f.write('hi')\n")
    assert report.blocked is False


def test_strict_mode_blocks_os_and_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_STRICT_IMPORTS", "1")
    report = analyze("import os\nopen('x.txt')\n")
    assert report.blocked is True
    types = {e.type for e in report.events}
    assert "blocked_import" in types
    assert "blocked_call" in types


def test_allowlist_contains_known_modules() -> None:
    assert "subprocess" in safety.BLOCKED_MODULES
    assert "socket" in safety.BLOCKED_MODULES
    assert "os" in safety.WARN_MODULES


def test_dotted_import_blocks_root() -> None:
    report = analyze("import urllib.parse\n")
    # urllib (root) is on the block list, so any submodule is blocked.
    assert report.blocked is True
