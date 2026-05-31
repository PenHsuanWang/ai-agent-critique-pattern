"""asyncpg connection pool management.

Lifecycle (called from FastAPI lifespan in main.py):
    await init_pool(dsn)   # on startup
    await close_pool()     # on shutdown

Usage in services/infrastructure:
    pool = get_pool()
    if pool:
        async with pool.acquire() as conn:
            ...

If DATABASE_URL is not configured, get_pool() returns None and the system
falls back to the in-memory OrchestratorStore. Log a warning to indicate
that state will be lost on server restart.
"""

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS orchestrator_sessions (
    session_id   TEXT        PRIMARY KEY,
    task         TEXT        NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'pending',
    state_json   TEXT        NOT NULL,
    enable_hitl  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orch_sessions_status
    ON orchestrator_sessions (status);
"""


async def init_pool(dsn: str) -> None:
    """Create the connection pool and ensure the schema exists."""
    global _pool
    try:
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
        logger.info("PostgreSQL connection pool initialized.")
    except Exception as exc:
        logger.error(
            "Failed to connect to PostgreSQL (%s). "
            "Falling back to in-memory store — state will NOT persist across restarts.",
            exc,
        )
        _pool = None


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")


def get_pool() -> Optional[asyncpg.Pool]:
    """Return the active pool, or None if not initialised."""
    return _pool
