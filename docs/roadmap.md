# Roadmap

## M0: Documentation Skeleton

Status: current repository.

Deliverables:

- README.
- Architecture documentation.
- Workflow documentation.
- Safety notes.
- Evaluation plan.
- Initial curriculum outline.
- Tutor system prompt.

## M1: CLI Prototype

Deliverables:

- Local command-line session.
- Ollama-compatible model adapter.
- Basic subprocess runner.
- Timeout handling.
- A few fixed exercises.
- JSON learner profile.

Exit criteria:

- Student can complete three Python exercises.
- Tutor gives hint-first feedback.
- Code is actually executed and tested.

## M2: Curriculum Engine

Deliverables:

- Lesson schema.
- Exercise schema.
- Rubric schema.
- Mastery criteria.
- Progress tracking.

Exit criteria:

- Tutor selects next exercise based on learner performance.
- Recurring mistake types are recorded.

## M3: Web UI

Deliverables:

- Local browser UI.
- Code editor.
- Test output panel.
- Hint ladder controls.
- Lesson navigation.

Exit criteria:

- Learner can use the system without terminal knowledge.

## M4: Stronger Sandboxing

Deliverables:

- Containerized execution option.
- Filesystem isolation.
- Network disabled by default.
- CPU and memory limits.
- Output truncation.

Exit criteria:

- Unsafe submissions are blocked or contained.
- The tutor can explain blocked code without exposing policy internals unnecessarily.

## M5: Offline Retrieval

Deliverables:

- Local Python docs index.
- Optional local package docs.
- Retrieval-aware model prompts.

Exit criteria:

- Tutor can cite local docs snippets internally while remaining offline.

## M6: Advanced Tracks

Candidate tracks:

- Python for automation.
- Python for network engineering.
- Python for cybersecurity scripting.
- Python for data analysis.
- Python testing with pytest.
- APIs with FastAPI.
- Async Python.

## M7: Model Optimization

Deliverables:

- Model benchmark suite.
- Prompt variants.
- Quantization comparison.
- Optional LoRA fine-tuning experiments.

Exit criteria:

- Clear recommendation for default local model by hardware class.
