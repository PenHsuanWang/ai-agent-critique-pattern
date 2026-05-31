# AI Agent Generator–Critique Pattern — Handbook

> **Version:** 0.6.0  
> **Last updated:** 2026-05-31  
> **Architecture basis:** 多代理人迴圈代理架構設計.md (design-doc/)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Design](#2-architecture-design)
3. [File Structure](#3-file-structure)
4. [Quick Start](#4-quick-start)
5. [Configuration Reference](#5-configuration-reference)
6. [API Reference](#6-api-reference)
7. [Core Design Patterns](#7-core-design-patterns)
8. [Infrastructure Layer](#8-infrastructure-layer)
9. [Agent System Deep Dive](#9-agent-system-deep-dive)
10. [HITL (Human-in-the-Loop) Guide](#10-hitl-human-in-the-loop-guide)
11. [Vector Episodic Memory Guide](#11-vector-episodic-memory-guide)
12. [Development Guide](#12-development-guide)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Project Overview

This project implements a **Decoupled Multi-Agent State Machine** that solves fundamental problems in multi-agent AI systems. Each problem was discovered through deep runtime analysis and fixed with a targeted, testable change.

| Problem | Root Cause | Solution |
|---|---|---|
| **Context Pollution** | Generator and Critique share session memory | Fully isolated `AgentSession` per agent per iteration; internal reasoning never leaves the session |
| **Confirmation Bias** | Critique sees Generator's reasoning and is anchored to it | Critique receives only the clean draft — never tool calls, thoughts, or intermediate steps |
| **Generator Amnesia (Brain Split)** | Fresh AgentSession wipes Generator's memory of its own prior draft | `previous_draft` injected into the revision prompt (Pattern 6) |
| **Generator Source Amnesia (Hallucination Risk)** | Generator assumes its document knowledge persists across iterations | Explicit "re-read source documents via tools" instruction in revision prompt (Pattern 6 extension) |
| **Critique Amnesia** | Fresh Critique AgentSession loses track of what issues it raised previously | `previous_critique.issues` injected as PREVIOUS EVALUATION CONTEXT (Pattern 8) |
| **Conversational Preamble Chaos** | LLMs prepend meta-commentary before the draft; Critique rejects for it | CRITICAL OUTPUT RULE in Generator prompt bans all preamble (Pattern 7) |

### The Two-Agent Loop

```
User Task
   │
   ▼
┌──────────────────────────────────────────────┐
│              OrchestratorService              │
│                                               │
│   ┌─────────────────┐   ┌─────────────────┐  │
│   │  Generator Agent │   │  Critique Agent  │  │
│   │  (ReAct Loop)   │──▶│  (ReAct Loop)   │  │
│   │                  │   │                  │  │
│   │  • Reads docs    │   │  • Verifies claims│ │
│   │  • Plans answer  │   │  • Checks logic  │  │
│   │  • Produces draft│   │  • Returns JSON  │  │
│   └─────────────────┘   └─────────────────┘  │
│           ▲                      │             │
│           └──── revision notes ──┘             │
│                (if not passed)                 │
└──────────────────────────────────────────────┘
          │ passed=True OR max_iterations
          ▼
      Final Output
```

### What Was Built

| Component | Status | Description |
|---|---|---|
| Generator ReAct Loop | ✅ | Full Claude ReAct loop with document tools + extended thinking |
| Critique ReAct Loop | ✅ | Claude ReAct loop with mandatory `submit_critique` tool |
| Orchestrator | ✅ | Parent controller with strict memory isolation (state filter) |
| Memory Isolation | ✅ | Deep-copy boundary; no shared AgentSession instances |
| PostgreSQL Checkpointer | ✅ | asyncpg-backed crash-safe state persistence |
| HITL Pause/Resume | ✅ | Pause on max_iterations + human approve/revise API |
| Vector Episodic Memory | ✅ | PostgreSQL + pgvector store for Critique historical patterns |
| REST API (FastAPI) | ✅ | `/api/v1/critique`, `/api/v1/sessions/{id}/state|resume`, `/api/v1/documents` |

---

## 2. Architecture Design

### Memory Isolation Matrix

The single most important invariant in the system:

```
                    Generator         Critique        Orchestrator
                    AgentSession      AgentSession     State
                    ─────────────     ─────────────   ─────────────
Generator sees:     ✅ own messages   ❌ NEVER        task + revision_notes only
Critique sees:      ❌ NEVER         ✅ own messages  task + clean draft only
Orchestrator sees:  ❌ raw traces    ❌ raw traces    CritiqueResult struct only
```

**What crosses the isolation boundary (the ONLY shared data):**

```
Generator → Orchestrator:   current_draft (plain string, no ReAct traces)
Critique  → Orchestrator:   CritiqueResult (typed dataclass: passed, issues, notes, confidence)
Orchestrator → Generator:   task + revision_notes (extracted from CritiqueResult only)
Orchestrator → Critique:    task + current_draft (clean text only)
```

### State Machine Lifecycle

```
OrchestratorState.status transitions:

  pending
     │  run() called
     ▼
  running
     │
     ├──[critique.passed == True]──────────────────▶ success
     │
     ├──[iteration_count >= max_iterations]
     │       ├──[enable_hitl == False]──────────────▶ max_iterations_reached
     │       └──[enable_hitl == True]───────────────▶ paused_for_hitl
     │                                                    │
     │                                              resume(action)
     │                                                    │
     │                                ┌─────────────────┤
     │                                │ approve          │ revise
     │                                ▼                  ▼
     │                             success            running (continues)
     │
     └──[agent exception]─────────────────────────────▶ error
```

### PostgreSQL Schema

```sql
CREATE TABLE orchestrator_sessions (
    session_id   TEXT        PRIMARY KEY,
    task         TEXT        NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'pending',
    state_json   TEXT        NOT NULL,   -- full OrchestratorState JSON
    enable_hitl  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orch_sessions_status ON orchestrator_sessions (status);
```

---

### Architecture Improvements (v0.6.0)

Vector Episodic Memory refactored from ChromaDB to PostgreSQL + pgvector:

| Change | Detail |
|---|---|
| **Dependency swap** | Removed `chromadb`; added `pgvector>=0.3.0` + `sentence-transformers>=3.0.0` |
| **Unified infrastructure** | Episodes now stored in the same PostgreSQL instance as session checkpoints — no separate ChromaDB file system path |
| **Native boolean metadata** | `passed` column is a true SQL `BOOLEAN` (ChromaDB forced `"true"`/`"false"` strings) |
| **Async-safe encoding** | `SentenceTransformer.encode()` wrapped in `run_in_executor` — CPU-bound tensor ops no longer block the asyncio event loop |
| **HNSW index** | `USING hnsw (embedding vector_cosine_ops)` for fast approximate nearest-neighbour search |
| **Startup-time schema** | `_setup()` creates extension + table + index on startup (idempotent `IF NOT EXISTS`) |
| **Guard for missing pool** | `VECTOR_MEMORY_ENABLED=true` without `DATABASE_URL` logs a warning and is skipped (previously would crash) |
| **Removed `VECTOR_MEMORY_PATH`** | Config field and `.env.example` entry removed — no longer needed |

### Architecture Improvements (v0.5.0)

The following structural defects were identified and fixed:

| Defect | Severity | Fix |
|---|---|---|
| Dead code — `api/v1/critique.py` had a second `router = APIRouter()` at line 150 that overwrote the HITL-aware handler, making the HITL endpoint unreachable | 🔴 Bug | Removed 114 lines of stale pre-HITL duplicate code |
| `infrastructure/checkpointer.py` imported `InMemoryOrchestratorStore` from `services/memory.py`, violating the layer boundary (infrastructure→service) | 🔴 Layer violation | Moved `InMemoryOrchestratorStore` into `checkpointer.py`; made all methods `async` (they were sync, so `await store.save(state)` would have raised `TypeError` at runtime in in-memory mode); deleted `services/memory.py` |
| `OrchestratorService._build_episodic_tools` used a deferred import (`# noqa: PLC0415`) mixing tool-assembly responsibility into the orchestrator | 🟡 SRP | Extracted `build_tool_pair(store)` factory into `episodic_memory_tools.py`; orchestrator now delegates with a single call |
| `_extract_text` and `_serialize_content` were identically defined in both `generator_agent.py` and `critique_agent.py` | 🟡 DRY | Centralised in `services/agent_utils.py` |
| `AsyncAnthropic` clients were module-level singletons, making unit testing require monkeypatching | 🟡 Testability | Client is now a constructor-injected parameter (`__init__(self, client=None)`) with a lazy default |
| `OrchestratorService` typed its injected stores as `Any`, with no explicit interface contract | 🟡 Type safety | Added `CheckpointerPort` and `EpisodicMemoryPort` Protocols in `domain/ports.py`; `OrchestratorService` now uses these types |
| Critique agent's tool dispatch used two different calling conventions for sync vs async handlers (`handler(dict)` vs `await handler(**kwargs)`) | 🟡 Maintainability | Unified via `call_handler(handler, input_dict)` in `agent_utils.py` |

---

## 3. File Structure

```
ai-agent-critique-pattern/
├── app/
│   ├── main.py                          # FastAPI factory + lifespan (startup wiring)
│   ├── core/
│   │   └── config.py                    # Pydantic-settings: all env vars
│   ├── domain/                          # Pure Python — no external dependencies
│   │   ├── models.py                    # AgentSession, CritiqueResult, OrchestratorState
│   │   ├── ports.py                     # CheckpointerPort, EpisodicMemoryPort (Protocols)
│   │   └── exceptions.py               # Typed error hierarchy
│   ├── infrastructure/                  # External system adapters
│   │   ├── database.py                  # asyncpg pool init/close + schema DDL
│   │   ├── checkpointer.py              # InMemoryOrchestratorStore + PostgreSQLOrchestratorStore + get_store()
│   │   └── vector_memory.py             # EpisodicMemoryStore (PostgreSQL + pgvector)
│   ├── services/
│   │   ├── agent_utils.py               # Shared: extract_text, serialize_content, call_handler
│   │   ├── generator_agent.py           # Generator ReAct loop (injectable AsyncAnthropic client)
│   │   ├── critique_agent.py            # Critique ReAct loop (injectable client, uniform call_handler)
│   │   ├── orchestrator.py              # Parent controller + HITL resume (typed Ports, build_tool_pair)
│   │   └── tools/
│   │       ├── common_tools.py          # list_local_documents, read_local_document
│   │       ├── critique_tools.py        # make_submit_critique_handler() closure factory
│   │       └── episodic_memory_tools.py # make_retrieve_critiques_handler() + build_tool_pair()
│   ├── schemas/
│   │   ├── critique.py                  # CritiqueRequest/Response, CritiqueResultSchema
│   │   ├── hitl.py                      # HITLResumeRequest, HITLSessionStateResponse
│   │   └── documents.py                 # Document CRUD schemas
│   └── api/v1/
│       ├── critique.py                  # POST /api/v1/critique
│       ├── hitl.py                      # GET/POST /api/v1/sessions/{id}/state|resume
│       └── documents.py                 # GET/POST/DELETE /api/v1/documents
├── local_data/                          # Document knowledge base (put .txt/.md/.csv files here)
├── design-doc/
│   ├── 多代理人迴圈代理架構設計.md         # Original Chinese architectural spec
│   ├── architecture.png                 # Original MVP architecture diagram
│   ├── architecture-diagram.jpg         # Generator–Critique architecture diagram (conceptual)
│   ├── cretique-agent-loop-deep-dive.jpg # Critique loop / memory isolation diagram (conceptual)
│   ├── system-sequential-flow.png       # Legacy single-agent sequence diagram
│   ├── technical-blog-critique-pattern-zh-tw.md
│   ├── vector_memory_pgvector_sdd.md
│   └── diagram_creation_guide.md
├── .env.example                         # Configuration template
├── pyproject.toml                       # Dependencies + tool config
├── CLAUDE.md                            # Copilot agent instructions
└── HANDBOOK.md                          # This file
```

---

## 4. Quick Start

### Prerequisites

- Python 3.12+
- An Anthropic API key (`claude-3-7-sonnet-20250219` or newer)
- *(Optional)* PostgreSQL 14+ for persistence + HITL
- *(Optional)* Internet access on first run if `VECTOR_MEMORY_ENABLED=true` (downloads ~90 MB embedding model)

### Installation

```bash
# 1. Clone / enter the project directory
cd ai-agent-critique-pattern

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -e .                    # production deps
pip install -e ".[dev]"             # + pytest, ruff, httpx

# 4. Configure environment
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### Run the Server

```bash
# Development (auto-reload on file changes)
uvicorn app.main:app --reload --port 8001

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 2
```

The API docs are available at:
- Swagger UI: http://localhost:8001/docs
- ReDoc:       http://localhost:8001/redoc

### Add Knowledge Base Documents

Drop plain-text `.txt` files into `local_data/`. The Generator and Critique agents can read them via the `list_local_documents` and `read_local_document` tools.

```bash
echo "The capital of France is Paris." > local_data/geography.txt
```

### First Request

```bash
curl -s -X POST http://localhost:8001/api/v1/critique \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "my-first-task",
    "task": "Summarise the key facts from all documents in the knowledge base.",
    "max_iterations": 2
  }' | python -m json.tool
```

---

## 5. Configuration Reference

All settings are read from environment variables (or `.env` file). Defined in `app/core/config.py`.

### Anthropic / Model

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `ANTHROPIC_BASE_URL` | `None` | Optional: proxy or gateway URL |
| `CLAUDE_MODEL` | `claude-3-7-sonnet-20250219` | Claude model for both agents |
| `MAX_RETRIES` | `2` | Anthropic SDK retry count |
| `GENERATOR_MAX_TOKENS` | `16000` | Max output tokens for Generator |
| `CRITIQUE_MAX_TOKENS` | `8192` | Max output tokens for Critique |

### Extended Thinking (Generator)

| Variable | Default | Description |
|---|---|---|
| `EXTENDED_THINKING` | `false` | Enable Claude's deep reasoning mode for the Generator |
| `THINKING_BUDGET_TOKENS` | `10000` | Token budget for thinking blocks |

> **Constraint:** `GENERATOR_MAX_TOKENS` must be **greater than** `THINKING_BUDGET_TOKENS`.  
> Extended thinking forces `temperature=1.0` at the Anthropic API level.

### Orchestration

| Variable | Default | Description |
|---|---|---|
| `MAX_ITERATIONS` | `3` | Default max Generator↔Critique cycles per request |
| `GENERATOR_MAX_TOOL_CALLS` | `15` | Max tool-call rounds per Generator invocation |
| `CRITIQUE_MAX_TOOL_CALLS` | `10` | Max tool-call rounds per Critique invocation |

The two inner-loop caps are independent of `MAX_ITERATIONS`. A Generator invocation that reads 10 documents uses 10 of its 15 allowed rounds before producing its draft; if it exhausts the cap without finishing, a `GeneratorLoopError` is raised with an actionable message. Increase these values for tasks that require deep document exploration; decrease them to reduce cost and prevent runaway spirals.

### PostgreSQL Checkpointer

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `None` | PostgreSQL DSN. **Leave unset for in-memory fallback.** |

**Format:** `postgresql://user:password@host:port/dbname`  
**Example:** `postgresql://agent:secret@localhost:5432/critique_agent`

When `DATABASE_URL` is set:
- The `orchestrator_sessions` table is auto-created on startup.
- State is persisted after every iteration and on completion.
- HITL pause/resume endpoints are fully functional.

When unset (development mode):
- `InMemoryOrchestratorStore` is used automatically.
- State is lost on server restart.
- A `WARNING` log is emitted at startup.

### Vector Episodic Memory

| Variable | Default | Description |
|---|---|---|
| `VECTOR_MEMORY_ENABLED` | `false` | Enable pgvector episodic memory for the Critique agent |

> **Requires** `DATABASE_URL` — episodes are stored in the same PostgreSQL instance as session checkpoints. Enabling without `DATABASE_URL` logs a warning and is silently skipped.
>
> On first use, the `all-MiniLM-L6-v2` sentence-transformer model (~90 MB) is downloaded and cached locally.

### Application

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment label (shown in /health) |
| `DEBUG` | `false` | Enable DEBUG-level logging |
| `LOCAL_DATA_DIR` | `local_data` | Directory scanned for knowledge base documents |

---

## 6. API Reference

### POST `/api/v1/critique`

**Run the Generator–Critique loop on a task.**

**Request body:**
```json
{
  "session_id": "task-001",
  "task": "Analyse and summarise the key architectural decisions in all documents.",
  "max_iterations": 3,
  "enable_hitl": false
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | ✅ | Unique task identifier for logging and state tracking |
| `task` | string | ✅ | The task for the agents. Max 32768 chars. |
| `max_iterations` | int (1–10) | ❌ | Default: 3 |
| `enable_hitl` | bool | ❌ | Default: false. Requires `DATABASE_URL`. |

**Response body:**
```json
{
  "session_id": "task-001",
  "final_output": "The documents describe...",
  "iterations_used": 2,
  "status": "success",
  "critique_history": [
    {
      "passed": false,
      "issues": ["Missing Section 3 analysis"],
      "revision_notes": "Include a dedicated analysis of Section 3.",
      "confidence_score": 0.85
    },
    {
      "passed": true,
      "issues": [],
      "revision_notes": "",
      "confidence_score": 0.97
    }
  ],
  "draft_history": ["First draft...", "Revised draft..."],
  "review_url": null
}
```

**`status` values:**

| Value | Meaning |
|---|---|
| `success` | Critique approved the draft |
| `max_iterations_reached` | Cap hit; best-effort draft returned |
| `paused_for_hitl` | Awaiting human review (`review_url` is populated) |
| `error` | Agent or orchestrator failure |

---

### GET `/api/v1/sessions/{session_id}/state`

**Inspect a session (especially useful for paused HITL sessions).**

**Response:** `HITLSessionStateResponse`
```json
{
  "session_id": "task-001",
  "status": "paused_for_hitl",
  "iteration_count": 3,
  "max_iterations": 3,
  "enable_hitl": true,
  "current_draft": "...",
  "critique_passed": false,
  "critique_issues": ["Issue 1", "Issue 2"],
  "critique_revision_notes": "Please revise...",
  "critique_confidence": 0.72,
  "final_output": "",
  "error_message": ""
}
```

---

### POST `/api/v1/sessions/{session_id}/resume`

**Resume a HITL-paused session.**

**Request body:**
```json
{
  "action": "approve",
  "human_feedback": "",
  "additional_iterations": 1
}
```

| Field | Type | Description |
|---|---|---|
| `action` | `"approve"` or `"revise"` | `approve`: accept current draft. `revise`: run more iterations. |
| `human_feedback` | string | Notes injected as revision guidance (used when `action="revise"`) |
| `additional_iterations` | int (1–10) | How many more iterations (used when `action="revise"`) |

---

### GET `/api/v1/documents`

List all supported documents in the `local_data/` directory.

### POST `/api/v1/documents`

Upload a new `.txt`, `.md`, or `.csv` document to the knowledge base.

### DELETE `/api/v1/documents/{filename}`

Remove a document from the knowledge base.

---

### GET `/health`

**Liveness probe.**

```json
{
  "status": "ok",
  "env": "development",
  "model": "claude-3-7-sonnet-20250219",
  "extended_thinking": false,
  "max_iterations": 3,
  "checkpointer": "in-memory",
  "vector_memory": false
}
```

---

## 7. Core Design Patterns

### Pattern 1: Per-Run Closure Factory (`submit_critique`)

The most critical pattern in the system. The Critique agent is *required* to call `submit_critique` exactly once — this is the only mechanism to produce a structured `CritiqueResult`.

**File:** `app/services/tools/critique_tools.py`

```python
def make_submit_critique_handler(result_holder: list[CritiqueResult]):
    """Returns a (name, callable) pair bound to a per-run result_holder list."""
    def _handler(input: dict) -> str:
        if result_holder:          # duplicate call guard
            return "Error: submit_critique already called."
        cr = CritiqueResult(
            passed=input["passed"],
            issues=input.get("issues", []),
            revision_notes=input.get("revision_notes", ""),
            confidence_score=input.get("confidence_score", 1.0),
        )
        result_holder.append(cr)
        return "Critique submitted successfully."
    return "submit_critique", _handler
```

**Why this pattern:**
- `result_holder` is a fresh `list` per `CritiqueAgentService.run()` call — no global mutable state.
- The handler returns a string (as required by the Anthropic tool-use protocol).
- Duplicate call protection prevents the agent from overwriting its evaluation.
- The `episodic_memory_tools.py` uses the same factory pattern for `retrieve_similar_critiques`.

### Pattern 2: State Filter (The Isolation Boundary)

**File:** `app/services/orchestrator.py` → `_build_revision_context()`

The Orchestrator is the *only* component that sees both agents. It acts as a strict data filter:

```python
@staticmethod
def _build_revision_context(state: OrchestratorState) -> str:
    # ONLY issues and revision_notes pass to the Generator.
    # The Critique agent's internal ReAct traces are NEVER forwarded.
    cr = state.critique_result
    issues_text = "\n".join(f"  {i+1}. {issue}" for i, issue in enumerate(cr.issues))
    ...
```

**What also crosses the boundary on revision iterations:** `state.current_draft` (the Generator's own prior output) is passed back as `previous_draft`. This is safe — it is the Generator's *own* text, not Critique reasoning traces. See Pattern 6 below.

### Pattern 3: Fresh AgentSession per Iteration

```python
# Generator gets a new session every iteration — nothing leaks from iteration N to N+1.
gen_session = AgentSession(
    agent_id=f"generator-{state.session_id}-iter{state.iteration_count}"
)
```

This is enforced structurally: the `AgentSession` dataclass holds the conversation history as a list of dicts. By constructing a new instance, there is zero possibility of accidental state sharing.

### Pattern 4: Serialisation Contract (to_dict / from_dict)

`OrchestratorState` and `CritiqueResult` both implement `to_dict()` / `from_dict()` for PostgreSQL persistence. The design uses **TEXT columns** (not JSONB) to avoid asyncpg JSONB codec registration complexity:

```python
# Save
state_json = json.dumps(state.to_dict(), ensure_ascii=False)
await conn.execute("INSERT ... state_json = $1", state_json)

# Load
row = await conn.fetchrow("SELECT state_json FROM ...")
data = json.loads(row["state_json"])
state = OrchestratorState.from_dict(data)
```

### Pattern 5: Dependency Injection via Setters

The `OrchestratorService` uses setter injection (not constructor injection or FastAPI `Depends()`) to keep the pattern consistent with the MVP singleton approach:

```python
orchestrator_service.set_checkpointer(checkpointer)  # called in main.py lifespan
orchestrator_service.set_episodic_memory(episodic_store)
```

Both methods are no-ops gracefully — if `_checkpointer is None`, checkpointing is skipped without errors.

### Pattern 6: Previous Draft Injection (Fixing Generator Amnesia + Source Amnesia)

**Problem A — Generator Amnesia:** Because each iteration creates a fresh `AgentSession`, the Generator has no memory of what it wrote in the previous iteration. Without its previous draft, it rewrites from scratch on every revision cycle — introducing new errors and destabilising the loop.

**Solution A:** The Orchestrator passes `state.current_draft` as `previous_draft` to the Generator on iterations 2+. The Generator receives it inside its initial user message, clearly delimited.

**Why this does NOT violate memory isolation:**  
`previous_draft` is the Generator's *own* output — not any Critique reasoning or internal traces. It is the same text already stored in `OrchestratorState.current_draft` (a plain string). Passing it back to the Generator is equivalent to showing someone their own previous work before asking them to revise it.

**Problem B — Generator Source Amnesia (Hallucination Risk):** When the Generator's AgentSession is wiped, it also loses the *contents* of every document it read. On a revision iteration, the Critique may ask it to correct a specific fact (e.g., "the date in Section 2 is wrong"). Without explicit instruction, the LLM will often hallucinate a plausible-sounding correction rather than call the tool to re-read the source file. This produces a draft that looks fixed but contains invented data.

**Solution B:** An explicit instruction is injected into the revision prompt immediately before the request to produce the new draft:

```
IMPORTANT: You are in a fresh session. Your memory of previously read documents
has been cleared. If you need to add or verify factual details to address these
issues, you MUST use your tools to re-read the source documents. Do not guess
or hallucinate details.
```

**Complete message structure on revision iterations:**
```
Please complete the following task:

<task>

━━━ YOUR PREVIOUS DRAFT ━━━
<previous plain-text draft>
━━━ END OF PREVIOUS DRAFT ━━━

━━━ REVISION REQUIRED ━━━
Your previous draft was reviewed and did not meet quality standards.
Address ALL of the following issues before producing your new draft:

<structured issues + revision_notes from CritiqueResult>
━━━ END OF REVISION NOTES ━━━

IMPORTANT: You are in a fresh session. Your memory of previously read documents
has been cleared. If you need to add or verify factual details to address these
issues, you MUST use your tools to re-read the source documents. Do not guess
or hallucinate details.

Produce an improved draft that fully resolves the issues listed above.
```

**Memory isolation is still fully preserved:** The Generator receives only its own prior text plus the structured issues/notes — never any Critique ReAct traces, tool calls, or internal reasoning.

### Pattern 7: No Conversational Preamble (Pure Output Contract)

**Problem:** LLMs naturally want to be conversational. After a revision request, Claude may prepend:
> "I have updated Section 2 to include the data about X as requested. Here is the revised draft: [actual draft content]"

Because the Orchestrator uses the Generator's full raw text output as `state.current_draft`, the Critique agent receives the conversational preamble as part of the draft. The Critique — instructed to evaluate professionalism and accuracy — will flag this preamble as unprofessional or out-of-scope, creating a rejection loop that cannot resolve.

**Solution:** The Generator system prompt includes a `CRITICAL OUTPUT RULE` that explicitly bans:
- Conversational lead-ins ("Here is the updated draft:")
- Change summaries ("I have revised Section 2 to address the feedback...")
- Explanatory wrappers ("Based on the critique, I have made the following changes...")

The rule states: *"Begin writing the draft content immediately — any conversational prefix will be treated as part of the draft and will cause rejection."*

**Belt-and-suspenders on the Critique side:** The Critique system prompt's `SCOPE BOUNDARY` section explicitly instructs the Critique *not* to penalise formatting style choices unrelated to clarity or completeness. This prevents a case where the Generator produces a minor preamble despite the rule and the Critique enters a loop over irrelevant form issues.

**Confirmed design property: No Scope Creep**

The architecture guarantees topic confinement through three complementary mechanisms:

| Mechanism | What it prevents |
|---|---|
| Task re-injection every iteration | Agents cannot drift off-topic — the root objective is always their first visible context |
| Fresh `AgentSession` per iteration | No conversational tangents building across rounds |
| Local-only document tools | Agents cannot fetch uncontrolled external data that would shift the domain |

These properties are structural, not heuristic — they hold regardless of model behaviour.

### Pattern 8: Previous Critique Injection (Fixing Critique Amnesia)

**Problem:** Each Critique iteration creates a fresh `AgentSession` (required for memory isolation). This wipes the Critique's own prior evaluation. On iteration 2, the Critic reads the revised draft *without knowing what issues it raised in iteration 1*. This produces two failure modes:

1. **Forgotten issues** — the Critic passes the revised draft even though the Generator only partially addressed the issues, because the Critic has no memory of what it asked for.
2. **Contradictory feedback** — the Critic raises the same issue again, or penalises the Generator for *adding* something the Critic previously asked for, because it doesn't remember making the request.

Both failure modes cause the loop to become chaotic and potentially endless.

**Solution:** The Orchestrator passes `state.critique_result` as `previous_critique` to `CritiqueAgentService.run()` on all iterations. The Critique receives a `PREVIOUS EVALUATION CONTEXT` block in its evaluation prompt:

```
━━━ PREVIOUS EVALUATION CONTEXT ━━━
In the previous iteration, you evaluated an earlier version of this draft
and identified the following issues that needed to be fixed:
- <issue 1>
- <issue 2>

Please verify if the Generator has successfully resolved these specific issues,
in addition to checking for any new or remaining problems.
━━━ END OF PREVIOUS EVALUATION CONTEXT ━━━
```

**What crosses the boundary (and why it is safe):**  
Only `previous_critique.issues` (a `list[str]`) is injected — the structured issue list from the prior `CritiqueResult`. Specifically **not** included: the Critique's internal ReAct traces, tool call history, reasoning steps, or intermediate thoughts. The issues list is already a filtered, structured output — it is the Critique's *own* conclusions, not any Generator internals.

**Behaviour on first iteration (iteration 1):**  
`state.critique_result` is `None` on the first iteration. The `previous_critique=None` case is handled gracefully — the `PREVIOUS EVALUATION CONTEXT` block is simply omitted and the Critique evaluates the draft fresh.

**Behaviour when previous critique passed:**  
If `previous_critique.passed == True` (e.g., in a HITL revise path where a human overrides an approved draft), `previous_critique.issues` is `[]`, so the block is skipped. Correct behaviour — the Critique evaluates the new draft without anchoring to a "passed" prior review.

**`CritiqueAgentService.run()` updated signature:**
```python
async def run(
    self,
    session: AgentSession,
    task: str,
    draft: str,
    previous_critique: CritiqueResult | None = None,  # ← Pattern 8
    extra_tool_defs: list[dict] | None = None,
    extra_tool_registry: dict[str, Any] | None = None,
) -> CritiqueResult:
```

---

## 8. Infrastructure Layer

### 8.1 PostgreSQL Checkpointer

**Files:** `app/infrastructure/database.py`, `app/infrastructure/checkpointer.py`

**Startup flow (main.py lifespan):**

```python
await init_pool(settings.database_url)   # creates pool + auto-creates table
pool = get_pool()
checkpointer = get_store(pool)           # returns PG store or in-memory fallback
orchestrator_service.set_checkpointer(checkpointer)
```

**Store interface:**
```python
await store.save(state)                  # upsert by session_id
await store.get(session_id)              # returns OrchestratorState or None
await store.delete(session_id)           # cleanup
await store.list_paused()               # returns all paused_for_hitl sessions
```

**Setting up PostgreSQL locally:**
```bash
# Docker (quickest)
docker run -d --name critique-db \
  -e POSTGRES_USER=agent \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=critique_agent \
  -p 5432:5432 postgres:16

# Set in .env
DATABASE_URL=postgresql://agent:secret@localhost:5432/critique_agent
```

### 8.2 Vector Episodic Memory

**File:** `app/infrastructure/vector_memory.py`

Uses PostgreSQL with the **pgvector** extension (no separate server needed — shares the existing `asyncpg` pool).

**Embedding model:** `all-MiniLM-L6-v2` (sentence-transformers)
- Loaded synchronously on startup via `SentenceTransformer('all-MiniLM-L6-v2')`
- Downloaded automatically on first use (~90 MB, requires internet)
- Cached locally by sentence-transformers after first download
- Encoding is offloaded to a thread-pool executor (`run_in_executor`) to avoid blocking the asyncio event loop

**PostgreSQL table:** `critique_episodes`  
**Distance function:** `<=>` (pgvector cosine distance, 0–1 scale)  
**Index:** HNSW (`vector_cosine_ops`) for approximate nearest-neighbour search

**Schema:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS critique_episodes (
    episode_id       TEXT             PRIMARY KEY,
    session_id       TEXT             NOT NULL,
    iteration        INTEGER          NOT NULL,
    passed           BOOLEAN          NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL,
    revision_notes   TEXT             NOT NULL DEFAULT '',
    document         TEXT             NOT NULL,
    embedding        vector(384)
);

CREATE INDEX IF NOT EXISTS idx_critique_episodes_hnsw
    ON critique_episodes USING hnsw (embedding vector_cosine_ops);
```

**Episode document format (what gets embedded):**
```
Task: <task description>
Issues:
- <issue 1>
- <issue 2>
```

**Metadata stored per episode (as typed SQL columns):**

| Column | Type | Notes |
|---|---|---|
| `session_id` | TEXT | Which orchestration session |
| `iteration` | INTEGER | Which iteration within the session |
| `passed` | BOOLEAN | Native bool (no string encoding needed — pgvector improvement over ChromaDB) |
| `confidence_score` | DOUBLE PRECISION | |
| `revision_notes` | TEXT | First 512 chars only |

**Startup sequence:**
```python
episodic_store = EpisodicMemoryStore(pool)   # loads model
await episodic_store._setup()                # CREATE EXTENSION + TABLE + INDEX
orchestrator_service.set_episodic_memory(episodic_store)
```

**Why `only_failed=True` is the default for queries:**  
Failed episodes encode what *went wrong* — recurring failure patterns are the most actionable signal for the Critique agent. Successful episodes are stored but not retrieved by default.

---

## 9. Agent System Deep Dive

**Diagram status:**  
The image files in `design-doc/` are useful for explaining the design intent, but they are **not all implementation-accurate**. Known divergences from current code:

| Diagram element | Diagram value | Actual value |
|---|---|---|
| Critique workspace — *Max Tool Calls* | 15 | 10 (`CRITIQUE_MAX_TOOL_CALLS`) |
| Vector Store label | "ChromaDB / pgvector" | **pgvector only** — ChromaDB removed in v0.6.0 |
| `submit_critique` signature shown | `(passed, feedback)` | `(passed, issues, revision_notes, confidence_score)` |
| Continuity paths (`previous_draft`, `previous_critique`) | Not shown | Implemented — see Patterns 6 & 8 |

For source-of-truth behaviour, use:

- `app/services/orchestrator.py`
- `app/services/generator_agent.py`
- `app/services/critique_agent.py`
- `app/services/tools/*.py`

### 9.1 Generator Agent

**File:** `app/services/generator_agent.py`

**Tools available:**
- `list_local_documents` — returns filenames in `local_data/`
- `read_local_document` — returns content of a specific file

**ReAct loop safety cap:** Controlled by `GENERATOR_MAX_TOOL_CALLS` (default 15). Prevents runaway tool-use spirals on complex tasks.

**Extended thinking:** When `EXTENDED_THINKING=true`, Claude is given a `thinking` block before generating its response. Thinking blocks are preserved in the `AgentSession.messages` list (via `_serialize_content()` using `.model_dump()`) to maintain continuity across tool call rounds.

**Output purity guarantee (CRITICAL OUTPUT RULE):** The Generator system prompt explicitly bans any conversational preamble or meta-commentary in the final response. The draft must begin immediately — no "Here is the updated draft:", no "I have revised Section 2 as requested.", no wrappers. This is enforced by the system prompt, not at parse-time; the constraint is necessary because the Orchestrator passes the Generator's raw text output directly to the Critique agent. Any conversational prefix would be treated as draft content and flagged as unprofessional by the Critique.

**Tool dispatch:** All tool calls in the Generator loop are routed through `call_handler` (same as the Critique — see §9.2). All common tools are synchronous, so `call_handler` delegates to `handler(input_dict)` in practice; but using the shared adapter means adding an async generator tool in future requires no change to the dispatch loop.

### 9.2 Critique Agent

**File:** `app/services/critique_agent.py`

**Tools available:**
- `list_local_documents` — verify claims against source documents
- `read_local_document` — read documents for evidence
- `retrieve_similar_critiques` *(injected when episodic memory is active)* — search historical failure patterns
- `submit_critique` — **mandatory terminal tool** — the only way to produce a `CritiqueResult`

**`run()` signature:**
```python
async def run(
    session: AgentSession,              # fresh, isolated — never reused
    task: str,                          # original task — always the root anchor
    draft: str,                         # clean Generator output — no ReAct traces
    previous_critique: CritiqueResult | None = None,  # Critique's own prior result
    extra_tool_defs: list[dict] | None = None,
    extra_tool_registry: dict[str, Any] | None = None,
) -> CritiqueResult
```

**`previous_critique` parameter (Critique Amnesia fix):**  
On iterations 2+, the Critique receives its own previous `CritiqueResult.issues` as a `PREVIOUS EVALUATION CONTEXT` block in the evaluation prompt. This gives the Critique logical continuity across iterations without violating the memory isolation contract: only the structured issues list is injected — never the Critique's internal ReAct traces.  
See Pattern 8 for full detail.

**ReAct loop safety cap:** Controlled by `CRITIQUE_MAX_TOOL_CALLS` (default 10). Prevents runaway tool-use spirals.

**Tool dispatch (`call_handler`):** Both the Generator and Critique agents route every tool call through the `call_handler` adapter from `services/agent_utils.py`. This unifies sync and async handler calling conventions at a single dispatch site:
```python
# services/agent_utils.py
async def call_handler(handler: Any, input_dict: dict[str, Any]) -> Any:
    if asyncio.iscoroutinefunction(handler):
        return await handler(**input_dict)   # async handlers: keyword args
    return handler(input_dict)               # sync handlers: full dict

# Usage in both generator_agent.py and critique_agent.py
result = await call_handler(handler, dict(block.input))
```
Exception handling is done by the caller (not inside `call_handler`) so the agent loop can decide whether to surface the error as a tool result or re-raise it. This is required because `retrieve_similar_critiques` is async (asyncpg/pgvector queries are I/O-bound), while common document tools and `submit_critique` are synchronous. The asymmetry between calling conventions (dict vs kwargs) reflects the respective tool registration contracts. `call_handler` preserves both while keeping the dispatch site to a single line.

**Scope boundary in system prompt:** The Critique agent is explicitly instructed **not** to penalise the draft for formatting style choices unrelated to clarity, nor for meta-commentary that the Critique itself may introduce during evaluation. This prevents false rejections driven by subjective preferences rather than objective quality gaps.

**Key enforcement:** The `submit_critique` call is the exit condition. The loop exits immediately once `submit_critique` is successfully called — no waiting for `end_turn`. This ensures the structured result is always captured even if Claude tries to say something after calling the tool.

**Rejection criteria (in system prompt):**
1. Factual inaccuracies or unsubstantiated claims
2. Missing information that is clearly relevant and available in documents
3. Logical inconsistencies or contradictions
4. Incomplete coverage of task requirements
5. Poor structure that makes the response difficult to understand

**Explicitly excluded from rejection criteria:**
- Absence or presence of titles/headers (unless the task requires them)
- Formatting style choices that do not affect clarity or completeness

This scope boundary prevents false rejections on form rather than substance.

**`submit_critique` schema:**
```json
{
  "passed": true,
  "issues": [],
  "revision_notes": "",
  "confidence_score": 0.95
}
```

### 9.3 Orchestrator

**File:** `app/services/orchestrator.py`

**The Orchestrator knows about both agents but shares nothing between them.**

The data flow on each side of the boundary is enforced by the pseudocode below. Lines marked `# ← boundary` are the only points where information crosses between agents.

```
run(state):
  while iteration_count < max_iterations:

    ── GENERATOR PHASE ──────────────────────────────────────────────────────
    1.  gen_session = AgentSession(...)           # fresh, isolated — zero prior memory
    2.  revision_context = _build_revision_context(state)
        # State Filter: extracts ONLY issues + revision_notes from CritiqueResult.
        # Critique ReAct traces, tool results, reasoning → discarded here.
    3.  previous_draft = state.current_draft      # Generator's own prior text (""  on iter 1)
    4.  draft = await generator.run(
            gen_session, task,
            revision_context,                     # ← boundary: structured issues only
            previous_draft,                       # ← boundary: Generator's own prior output
        )
    5.  state.current_draft = draft               # ← boundary: plain text only
        # gen_session → GC. All Generator internals are now gone.
    6.  await _checkpoint(state)

    ── CRITIQUE PHASE ───────────────────────────────────────────────────────
    7.  crit_session = AgentSession(...)          # fresh, isolated — zero prior memory
    8.  extra_tools = _build_episodic_tools()     # optional: episodic memory retrieval
    9.  critique_result = await critique.run(
            crit_session,
            task,                                 # ← boundary: original task (re-anchors scope)
            draft,                                # ← boundary: clean Generator output only
            previous_critique=state.critique_result,  # ← boundary: Critique's own prior issues
            extra_tools,
        )
    10. state.critique_result = critique_result   # ← boundary: CritiqueResult (typed dataclass)
        # crit_session → GC. All Critique internals are now gone.
    11. await _store_episode(state, critique_result)
    12. await _checkpoint(state)

    ── LOOP CONTROL ─────────────────────────────────────────────────────────
    13. if critique_result.passed → state.status = "success", return
    # else: loop continues; all three boundary payloads are ready for next iter

  if enable_hitl → state.status = "paused_for_hitl"
  else           → state.status = "max_iterations_reached"
```

**Complete boundary crossing summary (what each agent sees):**

| Agent | Receives FROM Orchestrator | Returns TO Orchestrator |
|---|---|---|
| **Generator** | `task` (original) · `revision_context` (issues + notes only) · `previous_draft` (its own prior output) | plain text draft |
| **Critique** | `task` (original) · `draft` (clean text) · `previous_critique.issues` (its own prior issue list) | `CritiqueResult` (typed dataclass) |

### 9.4 Complete Round-Trip Interaction Guarantees

One cycle = Generator run → Orchestrator filter → Critique run → Orchestrator filter.
The table below documents every known failure mode and the mechanism that prevents it.

| Failure Mode | Symptom | Prevention Mechanism | Pattern |
|---|---|---|---|
| **Context Pollution** | Critique sees Generator's tool calls / reasoning | Fresh `AgentSession` per agent per iteration | 3 |
| **Confirmation Bias** | Critique is anchored to Generator's thought process | State Filter: only clean text draft reaches Critique | 2 |
| **Generator Amnesia** | Generator rewrites from scratch instead of revising | `previous_draft` injection in revision prompt | 6 |
| **Generator Source Amnesia** | Generator hallucinates facts instead of re-reading docs | "Re-read source documents" instruction in revision prompt | 6 |
| **Critique Amnesia** | Critique forgets its own prior issues; contradictory feedback | `previous_critique.issues` injection in evaluation prompt | 8 |
| **Conversational Preamble** | Draft starts with meta-commentary; Critique rejects for it | `CRITICAL OUTPUT RULE` in Generator system prompt | 7 |
| **False Critique Rejection** | Critique penalises format, not substance | `SCOPE BOUNDARY` in Critique system prompt | 7 |
| **Scope Creep** | Agents drift off-topic over multiple iterations | Original task re-injected as first context every call | 7 |
| **Runaway Tool Spirals** | Agent calls tools indefinitely without concluding | `GENERATOR_MAX_TOOL_CALLS` / `CRITIQUE_MAX_TOOL_CALLS` caps | — |
| **Tool Exception → Loop Crash** | A tool raises an exception and kills the agent loop | `try/except` wraps all tool dispatch; error returned as string | — |

All prevention mechanisms are **structural** (enforced at the Python object/prompt level) — they hold regardless of model behaviour or specific task content.

---

## 10. HITL (Human-in-the-Loop) Guide

### When Does HITL Trigger?

HITL triggers when **all three conditions** are met:
1. `enable_hitl: true` in the request
2. `DATABASE_URL` is configured (state must be persisted)
3. `max_iterations` is reached without the Critique approving the draft

### HITL Workflow

```
Step 1: Submit task with enable_hitl=true
─────────────────────────────────────────
POST /api/v1/critique
{
  "session_id": "review-001",
  "task": "Write a technical architecture document.",
  "max_iterations": 2,
  "enable_hitl": true
}

Response (if max iterations reached without approval):
{
  "status": "paused_for_hitl",
  "review_url": "http://localhost:8001/api/v1/sessions/review-001/resume",
  "current_draft": "...",   ← empty final_output intentionally
  ...
}

Step 2: Inspect the paused session
───────────────────────────────────
GET /api/v1/sessions/review-001/state
→ Returns current draft, last critique issues, confidence score

Step 3a: Approve the current draft
────────────────────────────────────
POST /api/v1/sessions/review-001/resume
{ "action": "approve" }
→ Status becomes "success", final_output = current_draft

Step 3b: Request revisions with human guidance
────────────────────────────────────────────────
POST /api/v1/sessions/review-001/resume
{
  "action": "revise",
  "human_feedback": "The diagrams section is missing. Please add ASCII diagrams for each component.",
  "additional_iterations": 2
}
→ Human feedback is injected into revision_notes, loop resumes for 2 more iterations
```

### HITL Without a Database

If `DATABASE_URL` is not set and `enable_hitl: true` is requested, the system logs a warning and the HITL resume endpoint returns `503 Service Unavailable`. The main critique loop will still run but will return `max_iterations_reached` instead of `paused_for_hitl`.

---

## 11. Vector Episodic Memory Guide

### Enabling

```bash
# .env — both variables required
DATABASE_URL=postgresql://agent:secret@localhost:5432/critique_agent
VECTOR_MEMORY_ENABLED=true
```

> `VECTOR_MEMORY_ENABLED=true` without `DATABASE_URL` is silently skipped with a warning log.

### How It Works

1. **After every Critique run**, the Orchestrator stores an episode:
   - Task description + issues → embedded as a single 384-dim vector via `all-MiniLM-L6-v2`
   - Stored in `critique_episodes` table with `episode_id = "{session_id}::iter{iteration}"` (upsert-safe)
   - Metadata: `session_id`, `iteration`, `passed` (boolean), `confidence_score`, `revision_notes`

2. **Before the Critique agent evaluates each draft**, the `retrieve_similar_critiques` tool is injected into its tool registry.

3. **The Critique agent can call** `retrieve_similar_critiques` to surface historical failure patterns before forming its judgment:
   ```
   Tool: retrieve_similar_critiques
   Input: { "query": "architecture document missing diagrams", "n_results": 3 }
   
   Output:
   Found 2 similar historical critiques:
   
   --- Episode 1 (similarity: 87.3%, outcome: FAILED) ---
   Session: arch-task-019, Iteration: 2
   Issues identified:
     • Missing component interaction diagrams
     • No data flow documentation
   Revision notes: Add sequence diagrams for each API endpoint.
   ```

### Query Strategy

The `retrieve_similar_critiques` tool defaults to `only_failed=True` — it only surfaces failed episodes. This is by design: **failure patterns are the most actionable signal for preventing the same mistakes in new tasks.**

SQL executed under the hood:
```sql
SELECT session_id, iteration, passed, confidence_score, revision_notes,
       document, embedding <=> $1 AS distance
FROM   critique_episodes
WHERE  passed = FALSE
ORDER  BY distance
LIMIT  $2
```

### Cold Start

On first use, sentence-transformers downloads `all-MiniLM-L6-v2` (~90 MB). This happens at server startup (model is loaded in `EpisodicMemoryStore.__init__`). Subsequent starts load from local cache.

### Storage

Episodes live in the `critique_episodes` table in your PostgreSQL database. The HNSW index provides fast approximate nearest-neighbour search for high-dimensional vectors. No separate directory or file system path is needed.

---

## 12. Development Guide

### Running Linting

```bash
ruff check app/
ruff format app/
```

### Running Tests

```bash
pytest tests/ -v
```

### Testing Individual Components

```bash
# Test OrchestratorState serialization round-trip
python -c "
from app.domain.models import OrchestratorState, CritiqueResult
import json
state = OrchestratorState(session_id='test', task='demo', enable_hitl=True)
state.critique_result = CritiqueResult(passed=False, issues=['x'], confidence_score=0.7)
restored = OrchestratorState.from_dict(state.to_dict())
assert restored.critique_result.issues == ['x']
print('OK')
"

# Test tool closure isolation
python -c "
from app.services.tools.critique_tools import make_submit_critique_handler
from app.domain.models import CritiqueResult

holder1, holder2 = [], []
_, h1 = make_submit_critique_handler(holder1)
_, h2 = make_submit_critique_handler(holder2)
h1({'passed': True, 'issues': [], 'revision_notes': '', 'confidence_score': 1.0})
h2({'passed': False, 'issues': ['x'], 'revision_notes': 'fix', 'confidence_score': 0.5})
assert holder1[0].passed == True
assert holder2[0].passed == False
print('Isolation OK — holder1 and holder2 are independent')
"
```

### Adding New Tools

Both the Generator and Critique agents use tools registered as `(name, callable)` pairs.

**For a shared tool (available to both agents):**

1. Add the Anthropic tool definition to `COMMON_TOOL_DEFINITIONS` in `app/services/tools/common_tools.py`
2. Add the handler to `COMMON_TOOL_REGISTRY`

**For a Critique-only tool with per-run state (like `submit_critique` or `retrieve_similar_critiques`):**

1. Create a factory function in a new file under `app/services/tools/`:
   ```python
   def make_my_tool_handler(some_dependency) -> tuple[str, Callable]:
       async def _handler(input_arg: str) -> str:
           ...
           return "result string"
       return "my_tool_name", _handler
   ```
2. In `OrchestratorService._build_episodic_tools()` (or a new method), build the `(defs, registry)` pair and pass it to `critique_agent.run(extra_tool_defs=..., extra_tool_registry=...)`.

### Environment Modes

| Mode | `DATABASE_URL` | `VECTOR_MEMORY_ENABLED` | Behaviour |
|---|---|---|---|
| **Development** | unset | `false` | In-memory store, no vector memory. State lost on restart. |
| **Staging** | set | `false` | PostgreSQL persistence + HITL, no vector memory. |
| **Production** | set | `true` | Full feature set. First startup downloads embedding model (~90 MB). |

---

## 13. Troubleshooting

### Critique agent ends without calling `submit_critique`

**Symptom:** `CritiqueLoopError: Critique agent reached end_turn without calling submit_critique.`

**Cause:** Claude decided it had finished before calling the required tool.

**Fix options:**
1. Add `submit_critique` more prominently in the system prompt.
2. Increase `CRITIQUE_MAX_TOKENS` if Claude is running out of tokens.
3. Simplify the task — very long drafts may cause truncation.

---

### PostgreSQL connection fails at startup

**Symptom:** `WARNING: Failed to connect to PostgreSQL... Falling back to in-memory store`

**Check:**
```bash
# Verify PostgreSQL is running
psql "$DATABASE_URL" -c "SELECT 1"

# Verify the DSN format
# Correct:   postgresql://user:pass@host:5432/dbname
# Wrong:     postgres://...  (asyncpg requires postgresql://)
```

---

### Vector memory fails to initialise

**Symptom:** `ERROR: Failed to initialise vector episodic memory: ...`

**Most common causes:**

1. **`DATABASE_URL` not set** — pgvector requires PostgreSQL. Check:
   ```bash
   echo $DATABASE_URL
   ```

2. **pgvector extension not installed on the PostgreSQL server:**
   ```bash
   psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
   # If this fails, install pgvector on the server:
   # Ubuntu/Debian: apt-get install postgresql-16-pgvector
   # Docker: use postgres:16 image with pgvector already included,
   #         or use pgvector/pgvector:pg16 image.
   ```

3. **`pgvector` Python package missing:**
   ```bash
   pip install "pgvector>=0.3.0"
   # or with uv:
   uv sync
   ```

4. **`sentence-transformers` import error:**
   ```bash
   pip install "sentence-transformers>=3.0.0"
   ```

---

### Extended thinking + token budget error

**Symptom:** Anthropic API error about token budget.

**Fix:** Ensure `GENERATOR_MAX_TOKENS` > `THINKING_BUDGET_TOKENS`:
```bash
THINKING_BUDGET_TOKENS=10000
GENERATOR_MAX_TOKENS=16000   # must be strictly greater
```

---

### HITL resume returns 503

**Symptom:** `POST /api/v1/sessions/{id}/resume` → `503 Service Unavailable: Checkpointer not configured`

**Fix:** Set `DATABASE_URL` in `.env`. HITL requires persistent state — in-memory store cannot recover sessions across requests.

---

### Session not found on resume (404)

**Symptom:** `GET /api/v1/sessions/{id}/state` → `404 Not Found`

**Causes:**
1. Wrong `session_id` — check the `session_id` from the original `POST /api/v1/critique` response.
2. Server restarted without PostgreSQL — state was in-memory and is gone.
3. Session was already completed/deleted.

---

### Generator loop or Critique loop exceeds safety cap

**Symptom:** `GeneratorLoopError: Generator tool-call loop exceeded the safety cap of 15 rounds...`

**Cause:** The task requires more document reads than the inner loop allows, or the agent is cycling on a tool.

**Fix:** Increase the relevant cap in `.env`:
```bash
GENERATOR_MAX_TOOL_CALLS=25   # e.g., for tasks with large knowledge bases
CRITIQUE_MAX_TOOL_CALLS=15
```

---

### Critique rejects drafts in a loop over conversational preamble

**Symptom:** The loop reaches `max_iterations` without approval; Critique issues always mention "preamble", "meta-commentary", or "unprofessional introduction".

**Cause:** Despite the `CRITICAL OUTPUT RULE` in the Generator system prompt, a model variant is still prepending conversational text.

**Fix options:**
1. Verify the system prompt is loaded correctly:
   ```bash
   python -c "from app.services.generator_agent import _GENERATOR_SYSTEM_PROMPT; print('CRITICAL OUTPUT RULE' in _GENERATOR_SYSTEM_PROMPT)"
   ```
2. Strengthen the instruction by adding `tool_choice={"type": "auto"}` and a final user message nudge that starts with the word "Begin:" to anchor the output.
3. Add a thin post-processing strip in `OrchestratorService.run()` that trims known preamble patterns before assigning `state.current_draft`.

---

### Critique raises identical issues every iteration despite Generator addressing them

**Symptom:** The loop reaches `max_iterations`; each iteration's critique issues are identical or nearly identical to the previous one even though the draft visibly changed.

**Cause:** `previous_critique` is not flowing correctly through `CritiqueAgentService.run()` — the Critique evaluates each draft with no memory of what it previously asked for.

**Diagnosis:**
```bash
# 1. Confirm the run() signature accepts previous_critique
python -c "
import inspect
from app.services.critique_agent import CritiqueAgentService
sig = inspect.signature(CritiqueAgentService.run)
assert 'previous_critique' in sig.parameters, 'MISSING from signature!'
print('OK:', list(sig.parameters.keys()))
"

# 2. Confirm the evaluation prompt injects the PREVIOUS EVALUATION CONTEXT block
python -c "
from app.services.critique_agent import CritiqueAgentService
from app.domain.models import CritiqueResult
cr = CritiqueResult(passed=False, issues=['Missing Section X'], revision_notes='', confidence_score=0.5)
msg = CritiqueAgentService._build_evaluation_request('task', 'draft', cr)
assert 'PREVIOUS EVALUATION CONTEXT' in msg, 'Block NOT injected!'
print('OK: PREVIOUS EVALUATION CONTEXT block present')
"
```

**Fix:** Ensure `orchestrator.py` passes `previous_critique=state.critique_result` in the `self._critique.run(...)` call. On the first iteration `state.critique_result` is `None` — this is correct and handled gracefully.

---

### Generator produces hallucinated facts on revision iterations

**Symptom:** The Generator's revised draft contains plausible but incorrect details (dates, names, numbers) that differ from source documents; the Critique correctly rejects for factual inaccuracy each cycle.

**Cause:** The Generator is not re-reading source documents when revising because it incorrectly assumes its prior document knowledge persists in the fresh session.

**Diagnosis:** Check whether the "Source Amnesia" instruction is in the revision prompt:
```bash
python -c "
from app.services.generator_agent import GeneratorAgentService
msg = GeneratorAgentService._build_initial_message('task', 'some revision context', 'old draft')
assert 'fresh session' in msg, 'Source amnesia instruction missing!'
print('OK: source amnesia instruction present')
"
```

**Fix:** Verify `_build_initial_message` in `generator_agent.py` contains the `IMPORTANT: You are in a fresh session...` paragraph inside the `if revision_context:` branch (Pattern 6 extension).

---

### `OrchestratorState` serialization error

**Symptom:** `KeyError` or `TypeError` when loading state from PostgreSQL.

**Cause:** Schema mismatch between a new code version and data saved by an old version.

**Fix:** Add `data.get("new_field", default_value)` in `OrchestratorState.from_dict()` for any new fields, maintaining backward compatibility.

---

*End of Handbook*
