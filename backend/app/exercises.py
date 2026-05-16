"""Structured exercise loading and grading.

Each exercise is a JSON file in ``curriculum/exercises/`` matching the
schema documented in that directory's README. The module exposes:

* :func:`load_exercises` — read every ``*.json`` file under the exercise
  directory and return a name → :class:`Exercise` mapping. Files that
  fail validation are logged and skipped (so a single bad exercise
  can't break the whole API).
* :func:`grade` — combine a student submission with an exercise's
  visible+hidden tests, run it via the sandboxed runner, and produce
  a :class:`GradeResult` with per-test pass/fail status.

The exercise directory can be overridden with the ``TUTOR_EXERCISES_DIR``
environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .docs_refs import is_allowlisted
from .runner import RunResult, run_python
from .safety import analyze as analyze_safety


log = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "curriculum" / "exercises"


@dataclass(frozen=True)
class Exercise:
    id: str
    title: str
    section: str
    concepts: tuple[str, ...]
    prompt: str
    starter_code: str
    visible_tests: tuple[str, ...]
    hidden_tests: tuple[str, ...]
    references: tuple[str, ...]


def _coerce_str_list(value, *, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{name} entries must be strings")
        out.append(item)
    return tuple(out)


def _validate(payload: dict, *, source: Path) -> Exercise:
    required = ("id", "title", "section", "prompt", "starter_code")
    for key in required:
        if key not in payload or not isinstance(payload[key], str):
            raise ValueError(f"{source.name}: missing string field '{key}'")
    refs = _coerce_str_list(payload.get("references"), name="references")
    # Drop any reference that isn't on the docs allowlist; log it so
    # authoring problems are visible.
    filtered_refs: list[str] = []
    for url in refs:
        if is_allowlisted(url):
            filtered_refs.append(url)
        else:
            log.warning(
                "exercise %s: dropping non-allowlisted reference %s",
                payload["id"],
                url,
            )
    return Exercise(
        id=payload["id"],
        title=payload["title"],
        section=payload["section"],
        concepts=_coerce_str_list(payload.get("concepts"), name="concepts"),
        prompt=payload["prompt"],
        starter_code=payload["starter_code"],
        visible_tests=_coerce_str_list(
            payload.get("visible_tests"), name="visible_tests"
        ),
        hidden_tests=_coerce_str_list(
            payload.get("hidden_tests"), name="hidden_tests"
        ),
        references=tuple(filtered_refs),
    )


def exercises_dir() -> Path:
    raw = os.getenv("TUTOR_EXERCISES_DIR")
    return Path(raw) if raw else DEFAULT_DIR


def load_exercises(directory: Path | None = None) -> dict[str, Exercise]:
    """Load every ``*.json`` in *directory* (default: configured exercises dir).

    Files that fail to parse or validate are logged and skipped. Returns
    a mapping keyed by exercise id; later files with a duplicate id
    win, but a warning is emitted.
    """
    base = directory or exercises_dir()
    if not base.is_dir():
        return {}
    out: dict[str, Exercise] = {}
    for path in sorted(base.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("exercise file %s unreadable: %s", path, exc)
            continue
        try:
            ex = _validate(payload, source=path)
        except ValueError as exc:
            log.warning("exercise file %s invalid: %s", path, exc)
            continue
        if ex.id in out:
            log.warning("exercise id %s defined more than once", ex.id)
        out[ex.id] = ex
    return out


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


@dataclass
class TestOutcome:
    expr: str
    passed: bool
    error: str | None = None


@dataclass
class GradeResult:
    run: RunResult
    visible: list[TestOutcome] = field(default_factory=list)
    hidden: list[TestOutcome] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(o.passed for o in self.visible) and all(
            o.passed for o in self.hidden
        )


# A short harness appended to the student's code. Each test runs in
# isolation: failures are caught and surfaced via stdout as a JSON
# blob the grader parses. Using a sentinel and JSON keeps the protocol
# robust to whatever the student printed earlier.
_HARNESS_TEMPLATE = """
# --- begin tutor test harness ---
import json as _tutor_json
_tutor_results = []
_tutor_tests = {tests!r}
for _i, _expr in enumerate(_tutor_tests):
    try:
        exec(_expr, globals())
        _tutor_results.append({{"i": _i, "passed": True, "error": None}})
    except AssertionError as _e:
        _tutor_results.append({{"i": _i, "passed": False, "error": "AssertionError: " + str(_e)}})
    except BaseException as _e:
        _tutor_results.append({{"i": _i, "passed": False, "error": type(_e).__name__ + ": " + str(_e)}})
print()
print("__TUTOR_HARNESS__" + _tutor_json.dumps(_tutor_results))
# --- end tutor test harness ---
"""


def _build_program(student_code: str, tests: Iterable[str]) -> str:
    test_list = list(tests)
    return student_code.rstrip() + "\n" + _HARNESS_TEMPLATE.format(tests=test_list)


def _parse_harness(stdout: str, tests: list[str]) -> list[TestOutcome]:
    marker = "__TUTOR_HARNESS__"
    idx = stdout.rfind(marker)
    if idx == -1:
        # The harness never ran (e.g. import error / syntax error).
        return [
            TestOutcome(expr=t, passed=False, error="program did not reach tests")
            for t in tests
        ]
    payload = stdout[idx + len(marker):].strip().splitlines()[0]
    try:
        records = json.loads(payload)
    except json.JSONDecodeError:
        return [
            TestOutcome(expr=t, passed=False, error="harness output unreadable")
            for t in tests
        ]
    out: list[TestOutcome] = []
    by_index = {r.get("i"): r for r in records if isinstance(r, dict)}
    for i, expr in enumerate(tests):
        rec = by_index.get(i)
        if rec is None:
            out.append(TestOutcome(expr=expr, passed=False, error="missing result"))
            continue
        out.append(
            TestOutcome(
                expr=expr,
                passed=bool(rec.get("passed")),
                error=rec.get("error"),
            )
        )
    return out


def _strip_harness_output(stdout: str) -> str:
    """Remove the harness marker line so the student sees only their own output."""
    idx = stdout.rfind("__TUTOR_HARNESS__")
    if idx == -1:
        return stdout
    # Trim trailing blank line we added before the marker.
    cleaned = stdout[:idx].rstrip("\n")
    return cleaned + ("\n" if cleaned else "")


async def grade(
    exercise: Exercise,
    student_code: str,
    *,
    include_hidden: bool = True,
    timeout: float | None = None,
) -> GradeResult:
    """Run *student_code* against the exercise's tests and return outcomes."""
    visible_tests = list(exercise.visible_tests)
    hidden_tests = list(exercise.hidden_tests) if include_hidden else []
    all_tests = visible_tests + hidden_tests
    # Scan the student's portion only; the harness uses exec() to run
    # each test in isolation and would otherwise trip the scanner.
    student_safety = analyze_safety(student_code)
    if student_safety.blocked:
        # Build a short-circuit RunResult mirroring the runner's
        # blocked-result shape so the API contract stays stable.
        blocked_run = RunResult(
            stdout="",
            stderr=f"[safety] execution blocked: {student_safety.summary}\n",
            exit_code=-1,
            duration_ms=0,
            timed_out=False,
            truncated=False,
            blocked=True,
            safety_events=[
                {"type": e.type, "detail": e.detail, "lineno": e.lineno}
                for e in student_safety.events
            ],
        )
        outcomes = [
            TestOutcome(expr=t, passed=False, error="blocked by safety policy")
            for t in all_tests
        ]
        return GradeResult(
            run=blocked_run,
            visible=outcomes[: len(visible_tests)],
            hidden=outcomes[len(visible_tests):],
        )

    program = _build_program(student_code, all_tests)
    result = await run_python(program, timeout=timeout, skip_safety=True)

    outcomes = _parse_harness(result.stdout, all_tests)

    # Replace the harness chatter with a clean stdout the student sees.
    cleaned = RunResult(
        stdout=_strip_harness_output(result.stdout),
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        truncated=result.truncated,
        blocked=result.blocked,
        safety_events=list(result.safety_events),
    )
    visible_outcomes = outcomes[: len(visible_tests)]
    hidden_outcomes = outcomes[len(visible_tests):]
    return GradeResult(run=cleaned, visible=visible_outcomes, hidden=hidden_outcomes)
