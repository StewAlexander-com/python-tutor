# Architecture

This document describes the system architecture for an offline Python tutor powered by a local LLM such as Gemma.

## Design Premise

The LLM should act as the tutor, not the judge. Code correctness should be evaluated by running code, executing tests, checking expected outputs, and inspecting structured signals. The LLM receives those signals and turns them into understandable feedback.

## Component Diagram

```mermaid
flowchart TB
    subgraph Client
        UI[Local UI]
        Editor[Code Editor]
    end

    subgraph Application
        Orchestrator[Tutor Orchestrator]
        Lesson[Lesson Manager]
        Policy[Teaching Policy]
        Profile[Learner Profile]
    end

    subgraph Intelligence
        Adapter[LLM Adapter]
        Gemma[Local Gemma Model]
        RAG[Offline Docs Retrieval]
    end

    subgraph Verification
        Sandbox[Sandbox Runner]
        UnitTests[Unit Tests]
        StaticChecks[Static Checks]
        Rubric[Rubric Evaluator]
    end

    UI --> Orchestrator
    Editor --> Orchestrator
    Orchestrator --> Lesson
    Orchestrator --> Policy
    Orchestrator --> Profile
    Orchestrator --> Adapter
    Adapter --> Gemma
    Adapter --> RAG
    Orchestrator --> Sandbox
    Sandbox --> UnitTests
    Sandbox --> StaticChecks
    UnitTests --> Rubric
    StaticChecks --> Rubric
    Rubric --> Orchestrator
    Orchestrator --> UI
```

## Layers

### Interface Layer

The interface can be a CLI, a local web app, or a desktop app. The MVP should start with whichever path is fastest to build and debug. A web UI becomes useful once you want an embedded editor, visible test output, lesson navigation, and progress visualization.

### Orchestration Layer

The orchestrator is the control plane. It should be deterministic wherever possible. It chooses the current exercise, invokes the sandbox, prepares context for the LLM, applies the teaching policy, updates learner state, and decides whether mastery criteria have been met.

### Model Layer

The model adapter should hide the specific local inference backend. The application should not care whether the local model is served by Ollama, llama.cpp, LM Studio, vLLM, or a custom Transformers script.

Recommended adapter methods:

```text
generate(messages, temperature, max_tokens)
explain_error(context)
generate_hint(context)
generate_reflection_question(context)
```

### Verification Layer

The verification layer turns student code into evidence. Useful evidence includes:

- stdout
- stderr
- return code
- timeout state
- visible test results
- hidden test results
- static analysis findings
- syntax errors
- AST features used or missing

### State Layer

The state layer stores local learner history. This can start as JSON and later move to SQLite.

Suggested fields:

```text
learner_id
current_track
completed_lessons
attempt_history
recurring_errors
concept_mastery
preferred_hint_depth
last_session_summary
```

## Data Flow

```mermaid
sequenceDiagram
    participant S as Student
    participant UI as Tutor UI
    participant O as Orchestrator
    participant X as Sandbox
    participant T as Test Runner
    participant M as Local LLM
    participant DB as Learner State

    S->>UI: Submit code
    UI->>O: code + lesson id
    O->>X: execute safely
    X->>T: run tests
    T-->>O: results + errors
    O->>DB: record attempt
    O->>M: ask for hint using runtime evidence
    M-->>O: explanation + next step
    O-->>UI: feedback
    UI-->>S: hint, evidence, retry prompt
```

## Local-First Deployment

The default deployment should run entirely on the learner's machine:

```text
localhost UI
localhost tutor service
localhost model server
local sandbox
local SQLite or JSON state
local curriculum files
```

This keeps learner code, mistakes, and progress private.

## Extension Points

- Additional models: Gemma, Llama, Qwen, Phi, Mistral, or custom fine-tuned variants.
- Additional tracks: Python foundations, data analysis, web APIs, testing, automation, cybersecurity scripting.
- Additional assessment: property-based tests, mutation testing, style checks, complexity checks.
- Additional interfaces: VS Code extension, Jupyter integration, browser IDE, mobile companion.
