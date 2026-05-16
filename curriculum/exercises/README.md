# Structured Exercises

JSON files in this directory describe a single Python exercise each.
The backend loads every `*.json` here at startup (see
`backend/app/exercises.py`) and serves them via `GET /api/exercises`
and `GET /api/exercises/{id}`.

## Schema

```jsonc
{
  // Stable identifier (kebab.dotted). Must be unique across the file set.
  "id": "loops.counting-evens",

  // Human title shown in the lab.
  "title": "Count even numbers",

  // Curriculum section this maps to. Used by the frontend to surface
  // exercises alongside the matching lesson.
  "section": "Loops",

  // 0–5 free-form keywords; helpful for the LLM's evidence packet.
  "concepts": ["for loops", "counters", "modulo"],

  // Markdown prompt — what the student must implement.
  "prompt": "Write a function `count_even(numbers)` that returns the count of even integers in *numbers*.",

  // Code the editor is pre-populated with.
  "starter_code": "def count_even(numbers):\n    # your code here\n    return 0\n",

  // Visible tests are shown to the student; they're encouraged to read
  // and run them locally. Each entry is a pytest-style assertion or a
  // short `assert` statement appended to the student's code.
  "visible_tests": [
    "assert count_even([]) == 0",
    "assert count_even([1, 2, 3, 4]) == 2"
  ],

  // Hidden tests are run by the backend but never returned to the
  // frontend until after grading. Same syntax as visible_tests.
  "hidden_tests": [
    "assert count_even([2, 2, 2]) == 3",
    "assert count_even([1, 3, 5]) == 0"
  ],

  // Optional reference URLs surfaced in the evaluation evidence packet.
  // Must be on the docs allowlist (see backend/app/docs_refs.py); any
  // off-list URL is dropped silently.
  "references": [
    "https://docs.python.org/3/tutorial/controlflow.html#for-statements",
    "https://docs.python.org/3/reference/expressions.html#binary-arithmetic-operations"
  ]
}
```

## Authoring rules

* Keep visible tests few (1–3) and obvious — they exist to teach the
  shape of the API, not to catch every edge case.
* Hidden tests must each fail for a *different reason* so feedback can
  point at a specific gap.
* All `references` must be on the allowlist; the loader logs and drops
  off-list entries.

The `_seed` files in this directory are the starter set used in tests
and CI. Real curriculum exercises should be added as `*.json` siblings.
