# CLAUDE.md — Developer Guide for AI Agent Critique Pattern

## Project Overview
Multi-agent Generator–Critique loop built on FastAPI + Anthropic Python SDK.
Extends ai-agent-mvp with a second ReAct agent (Critic) that antagonises the first (Generator).

## Running the Server
```bash
uv sync
cp .env.example .env  # then add ANTHROPIC_API_KEY
uv run uvicorn app.main:app --reload --port 8001
```

## Key Architectural Constraints

### Memory Isolation (Non-negotiable)
- `AgentSession` is always instantiated fresh — never reused across agent roles or iterations.
- Generator's internal messages NEVER appear in Critique's session, and vice versa.
- The only cross-boundary data is the **final text draft** (Generator→Orchestrator) and the
  **structured CritiqueResult** (Critique→Orchestrator).

### State Filter
The state-filtered input boundary is implemented by:
- `OrchestratorService._build_revision_context()`
- `GeneratorAgentService._build_initial_message()`
- `CritiqueAgentService._build_evaluation_request()`

These are the places where cross-boundary data is explicitly constructed and
sanitised before entering a fresh agent session.

### Critique Output Contract
The Critique agent MUST call the `submit_critique` tool to signal completion.
`CritiqueAgentService.run()` raises `CritiqueLoopError` if the loop ends without a submission.

### Injectable Anthropic Client
Both `GeneratorAgentService` and `CritiqueAgentService` accept an optional `client: AsyncAnthropic`
parameter in `__init__`. Pass a mock in tests; omit in production for lazy default construction.

### Tool Dispatch Convention (`call_handler`)
`services/agent_utils.py::call_handler(handler, input_dict)` is the single dispatch point.
- **Async handlers** (e.g. `retrieve_similar_critiques`) receive `**input_dict` (kwargs).
- **Sync handlers** (e.g. `submit_critique`, common document tools) receive `input_dict` (full dict).
Do NOT replicate the inline `asyncio.iscoroutinefunction` pattern — use `call_handler`.

### Domain Ports
`domain/ports.py` defines `CheckpointerPort` and `EpisodicMemoryPort` as `@runtime_checkable`
Protocols. Use these types in `OrchestratorService` — never `Any` or concrete infrastructure classes.

## Adding New Generator Tools
1. Add implementation function in `app/services/tools/common_tools.py`
2. Add JSON schema entry to `COMMON_TOOL_DEFINITIONS`
3. Register in `COMMON_TOOL_REGISTRY`

## Adding New Critique Tools
1. Add implementation function in `app/services/tools/common_tools.py` (if shared)
   or `app/services/tools/critique_tools.py` (if critique-specific)
2. Register shared tools in `COMMON_TOOL_DEFINITIONS` / `COMMON_TOOL_REGISTRY`
3. For per-run critique tools, follow the `build_tool_pair()` pattern in
   `episodic_memory_tools.py`
   Note: `submit_critique` is always injected dynamically per-run; do NOT add a global singleton handler.

## Adding New Per-Run Stateful Critique Tools (like `retrieve_similar_critiques`)
1. Create a `make_<tool>_handler(dependency)` factory in a new file under `app/services/tools/`.
2. Create a `build_tool_pair(dependency) -> tuple[list[dict], dict[str, Callable]]` factory.
3. Build the pair in `OrchestratorService._build_episodic_tools()` (or a new similar method).
4. Pass to `critique_agent.run(extra_tool_defs=..., extra_tool_registry=...)`.

## Key Files (v0.6.0)
```
app/domain/ports.py               # CheckpointerPort, EpisodicMemoryPort Protocols
app/services/agent_utils.py       # extract_text, serialize_content, call_handler
app/infrastructure/checkpointer.py   # InMemoryOrchestratorStore (async) + PG store
app/infrastructure/vector_memory.py  # EpisodicMemoryStore: asyncpg + pgvector + SentenceTransformer
app/services/tools/episodic_memory_tools.py  # build_tool_pair() factory
app/services/memory.py            # Tombstone — class moved to infrastructure/checkpointer.py
```

## Environment Variables
See `.env.example` for full reference. Minimum required: `ANTHROPIC_API_KEY`.
Optional: `DATABASE_URL` (PostgreSQL, enables HITL + pgvector episodic memory), `VECTOR_MEMORY_ENABLED=true` (requires `DATABASE_URL`).
