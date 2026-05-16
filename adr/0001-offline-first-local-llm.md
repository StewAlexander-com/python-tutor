# ADR 0001: Offline-First Local LLM

## Status

Proposed.

## Context

The tutor should support private, local Python learning. Student code, errors, progress, and learning history may reveal sensitive personal or professional information. A local LLM such as Gemma allows the tutor to operate without sending learner data to a cloud model provider.

## Decision

The framework will be offline-first. The default inference path will use a local LLM adapter. The first target adapter should be compatible with a local HTTP model server such as Ollama.

The tutor will not rely on the LLM for correctness. Student code will be evaluated by deterministic tools such as syntax parsing, sandboxed execution, unit tests, static checks, and rubrics.

## Consequences

Positive:

- Learner data remains local by default.
- The app can work without internet access after setup.
- Model choice can be changed without changing core tutor logic.
- The deterministic test harness reduces hallucinated correctness.

Negative:

- Local inference quality depends on hardware and selected model size.
- Smaller models may need stronger prompt constraints.
- Setup complexity is higher than a hosted API.
- Sandboxing remains necessary even in a local-only app.

## Alternatives Considered

### Hosted Model API

This would likely improve response quality and reduce hardware requirements, but it would send learner data to a remote service and reduce offline usability.

### Fine-tuned Model First

Fine-tuning may improve tutor behavior, but it is not required for an MVP. Prompting plus deterministic verification should come first.

### No LLM

A purely rules-based tutor would be safer and more predictable, but it would be less flexible in explaining varied beginner mistakes.
