# AI Agent — Critique Pattern

## Overview

A multi-agent system built with **FastAPI** and the **Anthropic Python SDK** that implements the
**Generator–Critique (Review & Critique)** pattern described in the companion design document
(`design-doc/多代理人迴圈代理架構設計.md`).

Two independent ReAct agent loops run in a controlled antagonistic cycle:

| Agent | Role | Tools |
|---|---|---|
| **Generator** | Research, plan, and produce a candidate draft | `list_local_documents`, `read_local_document` |
| **Critique** | Critically evaluate the draft and find weaknesses | `list_local_documents`, `read_local_document`, `retrieve_similar_critiques` *(optional)*, `submit_critique` |

The **Orchestrator** acts as the parent controller. It enforces strict **memory isolation**
between the two agents — only structured, filtered state crosses the boundary between them.

```
User Task
    │
    ▼
┌──────────────────────────────────────────────┐
│          Orchestrator (Parent State)          │
│  iteration_count, current_draft, critique    │
└──────────┬───────────────────────────────────┘
           │ (1) task + revision_notes only
           ▼
   ┌───────────────┐     ReAct loop (isolated memory)
   │ Generator     │──── list_docs / read_doc ──▶ local_data/
   │ Agent Loop    │
   └───────┬───────┘
           │ (2) clean final draft text only (ReAct traces discarded)
           ▼
   ┌───────────────┐     ReAct loop (isolated memory)
   │ Critique      │──── list_docs / read_doc ──▶ local_data/
   │ Agent Loop    │──── submit_critique(passed, issues, notes) ──▶ result
   └───────┬───────┘
           │ (3) structured JSON: {passed, issues, revision_notes, confidence_score}
           ▼
┌──────────────────────────────────────────────┐
│  Loop control: passed? → exit  OR  iterate   │
│  Max iterations exceeded? → return best draft│
└──────────────────────────────────────────────┘
```

## Memory Isolation Guarantee

- Each agent gets a **fresh `AgentSession`** per iteration — no shared object references.
- The Generator's internal ReAct traces (tool calls, intermediate thoughts) are **never passed** to the Critique agent.
- The Critique agent's internal reasoning is **never passed** to the Generator.
- The only data crossing the boundary is:
  - Generator → Orchestrator: final text draft
  - Orchestrator → Critique: original task + clean draft
  - Critique → Orchestrator: structured `CritiqueResult` JSON

## Quick Start

```bash
# 1. Install dependencies (using uv)
uv sync

# 2. Configure environment
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY

# 3. (Optional) Add documents to the knowledge base
cp your_docs/*.md local_data/

# 4. Run the server
uv run uvicorn app.main:app --reload --port 8001
```

Open the interactive docs at http://localhost:8001/docs

## API Endpoints

### `POST /api/v1/critique`
Run the full Generator–Critique loop on a task.

**Request:**
```json
{
  "session_id": "task-001",
  "task": "Write a comprehensive analysis of...",
  "max_iterations": 3,
  "enable_hitl": false
}
```

**Response:**
```json
{
  "session_id": "task-001",
  "final_output": "...",
  "iterations_used": 2,
  "status": "success",
  "critique_history": [
    {
      "passed": false,
      "issues": ["Missing source citations", "Conclusion is too vague"],
      "revision_notes": "Add specific citations and expand conclusion.",
      "confidence_score": 0.85
    }
  ],
  "draft_history": ["draft 1 text...", "final approved draft..."],
  "review_url": null
}
```

**Status values:**
- `success` — Critique approved the output
- `max_iterations_reached` — Loop hit the iteration cap; best draft returned
- `paused_for_hitl` — Awaiting human review (`review_url` is set)
- `error` — Unexpected failure

### HITL (Human-in-the-Loop)
Requires `DATABASE_URL` to be configured.

- `GET  /api/v1/sessions/{session_id}/state` — inspect a paused session
- `POST /api/v1/sessions/{session_id}/resume` — approve or request revisions

```json
// Resume body
{ "action": "approve" }
// or
{ "action": "revise", "human_feedback": "Add diagrams.", "additional_iterations": 2 }
```

### Document Management
- `GET    /api/v1/documents` — list documents
- `POST   /api/v1/documents` — upload `.txt`, `.md`, `.csv`
- `DELETE /api/v1/documents/{filename}` — delete a document

## Extended Thinking

Set `EXTENDED_THINKING=true` in `.env` to enable Claude's extended thinking mode for the
Generator agent. Increase `GENERATOR_MAX_TOKENS` (e.g., `32000`) and set `THINKING_BUDGET_TOKENS`
(e.g., `20000`) to give the Generator more deep-reasoning capacity.

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. Anthropic API key. |
| `CLAUDE_MODEL` | `claude-3-7-sonnet-20250219` | Model for both agents. |
| `GENERATOR_MAX_TOKENS` | `16000` | Max tokens for Generator output. |
| `CRITIQUE_MAX_TOKENS` | `8192` | Max tokens for Critique output. |
| `EXTENDED_THINKING` | `false` | Enable extended thinking for Generator. |
| `THINKING_BUDGET_TOKENS` | `10000` | Token budget for Generator's thinking. |
| `MAX_ITERATIONS` | `3` | Max Generator↔Critique cycles. |
| `GENERATOR_MAX_TOOL_CALLS` | `15` | Max tool-call rounds per Generator invocation. |
| `CRITIQUE_MAX_TOOL_CALLS` | `10` | Max tool-call rounds per Critique invocation. |
| `LOCAL_DATA_DIR` | `local_data` | Directory for document knowledge base. |
| `DATABASE_URL` | `None` | PostgreSQL DSN. Leave unset for in-memory fallback. |
| `VECTOR_MEMORY_ENABLED` | `false` | Enable pgvector episodic memory for Critique. Requires `DATABASE_URL`. |
| `APP_ENV` | `development` | Environment label. |
| `DEBUG` | `false` | Enable debug logging. |

## Project Structure

```
app/
├── main.py                          # FastAPI app factory + lifespan
├── core/config.py                   # Pydantic-settings: all env vars
├── domain/                          # Pure Python — no external dependencies
│   ├── models.py                    # AgentSession, CritiqueResult, OrchestratorState
│   ├── ports.py                     # CheckpointerPort, EpisodicMemoryPort (Protocols)
│   └── exceptions.py                # Typed domain error hierarchy
├── infrastructure/                  # External system adapters
│   ├── database.py                  # asyncpg pool init/close + schema DDL
│   ├── checkpointer.py              # InMemoryOrchestratorStore + PostgreSQLOrchestratorStore
│   └── vector_memory.py             # EpisodicMemoryStore (PostgreSQL + pgvector)
├── services/
│   ├── agent_utils.py               # Shared: extract_text, serialize_content, call_handler
│   ├── generator_agent.py           # Generator ReAct loop
│   ├── critique_agent.py            # Critique ReAct loop + submit_critique enforcement
│   ├── orchestrator.py              # Parent controller + HITL resume
│   ├── memory.py                    # Tombstone — class moved to infrastructure/checkpointer.py
│   └── tools/
│       ├── common_tools.py          # list_local_documents, read_local_document
│       ├── critique_tools.py        # make_submit_critique_handler() factory
│       └── episodic_memory_tools.py # make_retrieve_critiques_handler() + build_tool_pair()
├── api/v1/
│   ├── critique.py                  # POST /api/v1/critique
│   ├── hitl.py                      # GET/POST /api/v1/sessions/{id}/state|resume
│   └── documents.py                 # Document CRUD endpoints
└── schemas/
    ├── critique.py                  # CritiqueRequest / CritiqueResponse
    ├── hitl.py                      # HITLResumeRequest, HITLSessionStateResponse
    └── documents.py                 # Document API schemas
```
