"""Tests for exercise loading, schema validation, grading, and the
related API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.exercises import Exercise, grade, load_exercises
from app.main import create_app


def _settings(**overrides) -> Settings:
    base = dict(
        ollama_url="http://ollama.test",
        model="gemma3:4b",
        request_timeout=5.0,
        allow_origins=("http://localhost:8000",),
        serve_frontend=False,
        frontend_dir=Path("/tmp/does-not-exist"),
        system_prompt="You are a Python tutor.",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_settings()))


# ----- loader ---------------------------------------------------------------


def test_loader_loads_seed_set() -> None:
    exercises = load_exercises()
    assert len(exercises) >= 5
    # Sanity-check one known exercise.
    ex = exercises["loops.counting-evens"]
    assert ex.title == "Count even numbers"
    assert ex.section == "Loops"
    assert any("docs.python.org" in r for r in ex.references)


def test_loader_drops_non_allowlisted_references(tmp_path: Path) -> None:
    payload = {
        "id": "test.references",
        "title": "Refs check",
        "section": "Test",
        "concepts": [],
        "prompt": "Nothing.",
        "starter_code": "pass\n",
        "visible_tests": [],
        "hidden_tests": [],
        "references": [
            "https://docs.python.org/3/tutorial/index.html",
            "https://evil.example.com/python",
        ],
    }
    (tmp_path / "ref.json").write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_exercises(tmp_path)
    ex = loaded["test.references"]
    assert ex.references == ("https://docs.python.org/3/tutorial/index.html",)


def test_loader_skips_invalid_files(tmp_path: Path) -> None:
    # Missing required field 'prompt'.
    (tmp_path / "broken.json").write_text(
        json.dumps({"id": "x.y", "title": "x", "section": "y", "starter_code": "pass"}),
        encoding="utf-8",
    )
    (tmp_path / "good.json").write_text(
        json.dumps(
            {
                "id": "good.one",
                "title": "Good",
                "section": "Test",
                "prompt": "p",
                "starter_code": "pass\n",
                "visible_tests": [],
                "hidden_tests": [],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_exercises(tmp_path)
    assert "good.one" in loaded
    assert "x.y" not in loaded


def test_loader_handles_unreadable_json(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json}", encoding="utf-8")
    loaded = load_exercises(tmp_path)
    assert loaded == {}


# ----- grading --------------------------------------------------------------


@pytest.mark.asyncio
async def test_grade_passes_correct_solution() -> None:
    ex = load_exercises()["loops.counting-evens"]
    solution = "def count_even(numbers):\n    return sum(1 for n in numbers if n % 2 == 0)\n"
    result = await grade(ex, solution)
    assert result.all_passed is True
    assert all(o.passed for o in result.visible)
    assert all(o.passed for o in result.hidden)


@pytest.mark.asyncio
async def test_grade_fails_buggy_solution() -> None:
    ex = load_exercises()["loops.counting-evens"]
    solution = "def count_even(numbers):\n    return 0  # buggy\n"
    result = await grade(ex, solution)
    assert result.all_passed is False
    assert any(not o.passed for o in result.visible)


@pytest.mark.asyncio
async def test_grade_handles_runtime_error_in_student_code() -> None:
    ex = load_exercises()["loops.counting-evens"]
    solution = "def count_even(numbers):\n    raise RuntimeError('oops')\n"
    result = await grade(ex, solution)
    assert result.all_passed is False
    # All tests recorded as failures with an error string.
    for outcome in result.visible:
        assert outcome.passed is False
        assert outcome.error


@pytest.mark.asyncio
async def test_grade_strips_harness_marker_from_stdout() -> None:
    ex = load_exercises()["loops.counting-evens"]
    solution = (
        "def count_even(numbers):\n"
        "    print('student says hi')\n"
        "    return sum(1 for n in numbers if n % 2 == 0)\n"
    )
    result = await grade(ex, solution)
    assert "__TUTOR_HARNESS__" not in result.run.stdout


# ----- API ------------------------------------------------------------------


def test_list_exercises_endpoint(client: TestClient) -> None:
    resp = client.get("/api/exercises")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 5
    ids = {item["id"] for item in body}
    assert "loops.counting-evens" in ids


def test_get_exercise_endpoint(client: TestClient) -> None:
    resp = client.get("/api/exercises/loops.counting-evens")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Count even numbers"
    assert "count_even" in body["starter_code"]
    assert body["visible_tests"]
    # Hidden tests must not be exposed via the detail endpoint.
    assert "hidden_tests" not in body


def test_get_unknown_exercise_returns_404(client: TestClient) -> None:
    resp = client.get("/api/exercises/no.such.exercise")
    assert resp.status_code == 404


def test_grade_endpoint_passing(client: TestClient) -> None:
    code = "def count_even(numbers):\n    return sum(1 for n in numbers if n % 2 == 0)\n"
    resp = client.post(
        "/api/exercises/loops.counting-evens/grade",
        json={"code": code},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["all_passed"] is True
    assert body["exercise_id"] == "loops.counting-evens"
    assert all(t["passed"] for t in body["visible"])


def test_grade_endpoint_failing(client: TestClient) -> None:
    resp = client.post(
        "/api/exercises/loops.counting-evens/grade",
        json={"code": "def count_even(numbers):\n    return 0\n"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["all_passed"] is False


def test_grade_endpoint_unknown_exercise(client: TestClient) -> None:
    resp = client.post(
        "/api/exercises/no.such/grade",
        json={"code": "pass\n"},
    )
    assert resp.status_code == 404


def test_config_exposes_exercise_count(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exercises_loaded"] >= 5
