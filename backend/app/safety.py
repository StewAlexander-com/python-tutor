"""Static safety checks for student Python submissions.

These checks are *defense in depth*, not a sandbox boundary. The
subprocess-based runner already enforces isolation, timeouts, and
resource limits; this module rejects clearly hostile patterns *before*
the subprocess even starts so that:

* obvious mistakes get a fast, readable error rather than a runtime
  failure inside the sandbox, and
* common bypass attempts (subprocess, os.system, socket, ctypes,
  multiprocessing, dynamic exec, raw file writes outside CWD) are
  surfaced as ``safety_events`` the API can return.

The checker walks the AST and flags imports and calls. It does NOT try
to be exhaustive — a determined attacker can dodge a static scanner
trivially. The real defence is the subprocess sandbox.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field


# Modules we always block. These are either networking, process control,
# native code loading, or low-level system interfaces.
BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "subprocess",
        "socket",
        "socketserver",
        "ssl",
        "asyncio.subprocess",
        "multiprocessing",
        "multiprocessing.pool",
        "ctypes",
        "ctypes.util",
        "cffi",
        "urllib",
        "urllib.request",
        "urllib2",
        "http",
        "http.client",
        "http.server",
        "httplib",
        "httpx",
        "requests",
        "aiohttp",
        "ftplib",
        "telnetlib",
        "smtplib",
        "poplib",
        "imaplib",
        "xmlrpc",
        "xmlrpc.client",
        "xmlrpc.server",
        "pickle",
        "shelve",
        "marshal",
        "pty",
        "fcntl",
        "resource",
        "signal",
        "winreg",
        "_winreg",
        "msvcrt",
    }
)


# These are flagged but not blocked by default. The tutor may want to
# allow ``os`` and ``pathlib`` for legitimate teaching, so we only block
# specific call patterns on them (see _DANGEROUS_CALLS below).
WARN_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "os.path",
        "pathlib",
        "shutil",
        "tempfile",
        "glob",
        "importlib",
    }
)


# Fully-qualified call patterns that are blocked outright regardless of
# module-level acceptance. These are the patterns the threat model in
# docs/safety-and-sandboxing.md calls out as dangerous.
_DANGEROUS_CALLS: frozenset[str] = frozenset(
    {
        "os.system",
        "os.popen",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
        "os.spawnl",
        "os.spawnv",
        "os.fork",
        "os.kill",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.removedirs",
        "shutil.rmtree",
        "shutil.move",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "socket.socket",
        "socket.create_connection",
        "importlib.import_module",
        "compile",
        "eval",
        "exec",
        "__import__",
    }
)


# Calls only blocked in strict mode. ``open()`` is common in beginner
# exercises ("read a file") so we keep it permitted by default; the
# tempdir, file-size rlimit, and lack of paths outside CWD limit damage.
_STRICT_DANGEROUS_CALLS: frozenset[str] = frozenset({"open"})


@dataclass(frozen=True)
class SafetyEvent:
    """A single static finding."""

    type: str  # "blocked_import", "blocked_call", "syntax_error"
    detail: str
    lineno: int | None = None


@dataclass
class SafetyReport:
    """Outcome of static analysis."""

    blocked: bool = False
    events: list[SafetyEvent] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.events:
            return ""
        return "; ".join(f"{e.type}: {e.detail}" for e in self.events)


def _qualified_name(node: ast.AST) -> str | None:
    """Return ``a.b.c`` for an Attribute/Name chain, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def _strict_mode() -> bool:
    """When TUTOR_STRICT_IMPORTS=1, also block WARN_MODULES."""
    return os.getenv("TUTOR_STRICT_IMPORTS", "0") == "1"


def analyze(code: str) -> SafetyReport:
    """Return a :class:`SafetyReport` for *code*.

    Never raises — a syntax error is reported as an event with
    ``blocked=False`` so the runner can still surface the parser
    diagnostic to the student. Imports of clearly hostile modules or
    direct calls to dangerous functions set ``blocked=True``.
    """
    report = SafetyReport()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        # Don't block on syntax — the runner will return the parser
        # error verbatim and that's far more useful to a student.
        report.events.append(
            SafetyEvent(
                type="syntax_error",
                detail=str(exc.msg or exc),
                lineno=exc.lineno,
            )
        )
        return report

    strict = _strict_mode()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if alias.name in BLOCKED_MODULES or root in BLOCKED_MODULES:
                    report.blocked = True
                    report.events.append(
                        SafetyEvent(
                            type="blocked_import",
                            detail=alias.name,
                            lineno=node.lineno,
                        )
                    )
                elif strict and (
                    alias.name in WARN_MODULES or root in WARN_MODULES
                ):
                    report.blocked = True
                    report.events.append(
                        SafetyEvent(
                            type="blocked_import",
                            detail=alias.name,
                            lineno=node.lineno,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = _module_root(mod)
            if mod in BLOCKED_MODULES or root in BLOCKED_MODULES:
                report.blocked = True
                report.events.append(
                    SafetyEvent(
                        type="blocked_import",
                        detail=mod,
                        lineno=node.lineno,
                    )
                )
            elif strict and (mod in WARN_MODULES or root in WARN_MODULES):
                report.blocked = True
                report.events.append(
                    SafetyEvent(
                        type="blocked_import",
                        detail=mod,
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.Call):
            qname = _qualified_name(node.func)
            if qname and qname in _DANGEROUS_CALLS:
                report.blocked = True
                report.events.append(
                    SafetyEvent(
                        type="blocked_call",
                        detail=qname,
                        lineno=getattr(node, "lineno", None),
                    )
                )
            elif qname and strict and qname in _STRICT_DANGEROUS_CALLS:
                report.blocked = True
                report.events.append(
                    SafetyEvent(
                        type="blocked_call",
                        detail=qname,
                        lineno=getattr(node, "lineno", None),
                    )
                )

    return report
