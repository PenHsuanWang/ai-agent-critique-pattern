"""Checkpointer backends for OrchestratorState persistence.

Two implementations satisfy CheckpointerPort:

  InMemoryOrchestratorStore   — dict-backed, process-scoped (dev / test mode).
  PostgreSQLOrchestratorStore — asyncpg-backed, crash-safe (production).

Both expose the same async interface:

    store.save(state)            # checkpoint after every iteration
    store.get(session_id)        # crash-recovery / HITL resume
    store.delete(session_id)     # cleanup on final completion

State serialisation
───────────────────
OrchestratorState.to_dict() produces a plain dict (no custom types), which is
dumped to JSON text and stored in the ``state_json`` TEXT column.  Using TEXT
(rather than JSONB) avoids the asyncpg codec registration that JSONB requires
and keeps the code simple.

Fallback
────────
get_store(pool) returns:
  - PostgreSQLOrchestratorStore  when pool is not None
  - InMemoryOrchestratorStore    when pool is None  (development/test mode)

Layer note
──────────
InMemoryOrchestratorStore was previously defined in services/memory.py and
imported here, creating an infrastructure→service layer violation.  It is
now defined directly in this module where it belongs.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.domain.models import OrchestratorState

logger = logging.getLogger(__name__)


# ── In-memory fallback ────────────────────────────────────────────────────── #


class InMemoryOrchestratorStore:
    """Dict-backed checkpointer for development and testing.

    All methods are async to satisfy CheckpointerPort and allow the
    Orchestrator to await them uniformly regardless of backend.
    Swapping to a Redis/PostgreSQL backend requires replacing this class only.
    """

    def __init__(self) -> None:
        self._store: dict[str, OrchestratorState] = {}

    async def save(self, state: OrchestratorState) -> None:
        self._store[state.session_id] = state

    async def get(self, session_id: str) -> Optional[OrchestratorState]:
        return self._store.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    async def list_paused(self) -> list[OrchestratorState]:
        return [s for s in self._store.values() if s.status == "paused_for_hitl"]

    @property
    def active_sessions(self) -> int:
        return len(self._store)


class PostgreSQLOrchestratorStore:
    """Persistent checkpointer backed by asyncpg.

    All operations are async to avoid blocking the FastAPI event loop.
    """

    def __init__(self, pool) -> None:  # pool: asyncpg.Pool
        self._pool = pool

    # ── Public interface ─────────────────────────────────────────────────── #

    async def save(self, state: OrchestratorState) -> None:
        """Insert or update the serialised state snapshot."""
        state_json = json.dumps(state.to_dict(), ensure_ascii=False)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_sessions
                    (session_id, task, status, state_json, enable_hitl, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (session_id)
                DO UPDATE SET
                    task        = EXCLUDED.task,
                    status      = EXCLUDED.status,
                    state_json  = EXCLUDED.state_json,
                    enable_hitl = EXCLUDED.enable_hitl,
                    updated_at  = NOW()
                """,
                state.session_id,
                state.task,
                state.status,
                state_json,
                state.enable_hitl,
            )
        logger.debug("Checkpointed session %s (status=%s)", state.session_id, state.status)

    async def get(self, session_id: str) -> Optional[OrchestratorState]:
        """Load a session by ID, or return None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state_json FROM orchestrator_sessions WHERE session_id = $1",
                session_id,
            )
        if row is None:
            return None
        data = json.loads(row["state_json"])
        return OrchestratorState.from_dict(data)

    async def delete(self, session_id: str) -> None:
        """Remove a session record (call after final completion if desired)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM orchestrator_sessions WHERE session_id = $1",
                session_id,
            )

    async def list_paused(self) -> list[OrchestratorState]:
        """Return all sessions currently awaiting human review."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT state_json FROM orchestrator_sessions WHERE status = 'paused_for_hitl'"
            )
        return [OrchestratorState.from_dict(json.loads(r["state_json"])) for r in rows]


def get_store(pool) -> PostgreSQLOrchestratorStore | InMemoryOrchestratorStore:
    """Return the appropriate store based on pool availability."""
    if pool is not None:
        return PostgreSQLOrchestratorStore(pool)
    logger.warning(
        "DATABASE_URL not set or connection failed — using in-memory store. "
        "State will be lost on server restart."
    )
    return InMemoryOrchestratorStore()
