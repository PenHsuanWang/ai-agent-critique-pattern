"""Vector Episodic Memory backed by PostgreSQL + pgvector.

The Critique agent's long-term memory: every completed critique is stored as an
episode. Before evaluating a new draft, the Critique agent can query historical
episodes to surface recurring patterns, known failure modes, and previously
flagged issues — preventing confirmation bias by grounding evaluation in evidence.

Storage layout (PostgreSQL table: ``critique_episodes``)
────────────────────────────────────────────────────────────────────────────────
episode_id       TEXT             PRIMARY KEY   — "{session_id}::iter{iteration}"
session_id       TEXT             NOT NULL
iteration        INTEGER          NOT NULL
passed           BOOLEAN          NOT NULL
confidence_score DOUBLE PRECISION NOT NULL
revision_notes   TEXT             NOT NULL      — first 512 chars
document         TEXT             NOT NULL      — embedded text (task + issues)
embedding        vector(384)                   — all-MiniLM-L6-v2 dense vector

Index: HNSW on embedding using cosine distance (vector_cosine_ops)
  — approximate nearest-neighbour search; fast for high-dimensional retrieval.

Dependencies
────────────
pgvector>=0.3.0        — registers the vector type codec with asyncpg
sentence-transformers  — local all-MiniLM-L6-v2 model (no external API calls)

The embedding model (~90 MB) is downloaded once on first startup and cached
locally by sentence-transformers. Requires internet access on first run.

Fallback: if VECTOR_MEMORY_ENABLED=false (default), EpisodicMemoryStore is
never instantiated and the Critique agent operates without historical context.
Requires DATABASE_URL to be set — pgvector lives inside the existing PG pool.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial

import asyncpg
from pgvector.asyncpg import register_vector
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384

# ── DDL ──────────────────────────────────────────────────────────────────── #

_SETUP_SQL = """
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
"""

# ── DML ──────────────────────────────────────────────────────────────────── #

_UPSERT_SQL = """
INSERT INTO critique_episodes
    (episode_id, session_id, iteration, passed, confidence_score,
     revision_notes, document, embedding)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (episode_id) DO UPDATE SET
    passed           = EXCLUDED.passed,
    confidence_score = EXCLUDED.confidence_score,
    revision_notes   = EXCLUDED.revision_notes,
    document         = EXCLUDED.document,
    embedding        = EXCLUDED.embedding
"""

_QUERY_SQL_FAILED = """
SELECT session_id, iteration, passed, confidence_score, revision_notes,
       document, embedding <=> $1 AS distance
FROM   critique_episodes
WHERE  passed = FALSE
ORDER  BY distance
LIMIT  $2
"""

_QUERY_SQL_ALL = """
SELECT session_id, iteration, passed, confidence_score, revision_notes,
       document, embedding <=> $1 AS distance
FROM   critique_episodes
ORDER  BY distance
LIMIT  $2
"""


# ── Domain model ─────────────────────────────────────────────────────────── #


@dataclass
class EpisodeRecord:
    """A single recalled episode returned by a similarity query."""

    session_id: str
    iteration: int
    task_summary: str
    issues: list[str]
    revision_notes: str
    passed: bool
    confidence_score: float
    distance: float = 0.0  # cosine distance — lower = more similar


# ── Repository ───────────────────────────────────────────────────────────── #


class EpisodicMemoryStore:
    """PostgreSQL + pgvector episodic memory for the Critique agent.

    Usage
    ─────
    store = EpisodicMemoryStore(pool)
    await store._setup()          # call once on startup — creates schema
    await store.store_episode(…)
    episodes = await store.query_similar("task description", n_results=3)
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        # Load embedding model synchronously — one-time cost at startup.
        logger.info("Loading sentence-transformer model '%s'…", _MODEL_NAME)
        self._encoder = SentenceTransformer(_MODEL_NAME)
        logger.info(
            "Episodic memory store initialised (model=%s, dim=%d)",
            _MODEL_NAME,
            _EMBEDDING_DIM,
        )

    # ── Setup ─────────────────────────────────────────────────────────────── #

    async def _setup(self) -> None:
        """Create pgvector extension, table, and HNSW index (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_SETUP_SQL)
        logger.info("Episodic memory schema ready (critique_episodes + HNSW index).")

    # ── Embedding ─────────────────────────────────────────────────────────── #

    async def _encode(self, text: str) -> list[float]:
        """Encode text to a 384-dim vector, offloaded to a thread-pool executor.

        ``SentenceTransformer.encode`` is CPU-bound (PyTorch tensor ops).
        Running it via ``run_in_executor`` prevents blocking the event loop
        under concurrent requests.
        """
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None, partial(self._encoder.encode, text)
        )
        return embedding.tolist()

    # ── Write ────────────────────────────────────────────────────────────── #

    async def store_episode(
        self,
        session_id: str,
        iteration: int,
        task: str,
        issues: list[str],
        revision_notes: str,
        passed: bool,
        confidence_score: float,
    ) -> None:
        """Embed and persist a critique episode (upsert — idempotent by episode_id).

        The embedding document concatenates the task summary and the issue strings
        so that both problem domain and specific failure modes are captured in the
        same vector space.
        """
        episode_id = f"{session_id}::iter{iteration}"
        issues_text = "\n".join(f"- {i}" for i in issues) if issues else "(none)"
        document = f"Task: {task}\nIssues:\n{issues_text}"

        embedding = await self._encode(document)

        async with self._pool.acquire() as conn:
            await register_vector(conn)
            await conn.execute(
                _UPSERT_SQL,
                episode_id,
                session_id,
                iteration,
                passed,
                float(confidence_score),
                revision_notes[:512],
                document,
                embedding,
            )
        logger.debug("Stored episode %s (passed=%s)", episode_id, passed)

    # ── Read ─────────────────────────────────────────────────────────────── #

    async def query_similar(
        self,
        query_text: str,
        n_results: int = 3,
        only_failed: bool = True,
    ) -> list[EpisodeRecord]:
        """Return the n most semantically similar historical episodes.

        Parameters
        ----------
        query_text  : description of the current task / draft excerpt
        n_results   : maximum number of episodes to return
        only_failed : if True, exclude passed episodes — failed episodes encode
                      what went wrong and are the most actionable signal for the
                      Critique agent
        """
        query_embedding = await self._encode(query_text)
        sql = _QUERY_SQL_FAILED if only_failed else _QUERY_SQL_ALL

        try:
            async with self._pool.acquire() as conn:
                await register_vector(conn)
                rows = await conn.fetch(sql, query_embedding, n_results)
        except Exception as exc:
            logger.warning("Episodic memory query failed: %s", exc)
            return []

        episodes: list[EpisodeRecord] = []
        for row in rows:
            issues = _parse_issues_from_document(row["document"])
            episodes.append(
                EpisodeRecord(
                    session_id=row["session_id"],
                    iteration=int(row["iteration"]),
                    task_summary=row["document"],
                    issues=issues,
                    revision_notes=row["revision_notes"] or "",
                    passed=bool(row["passed"]),
                    confidence_score=float(row["confidence_score"]),
                    distance=float(row["distance"]),
                )
            )
        return episodes

    async def count(self) -> int:
        """Return total number of stored episodes."""
        async with self._pool.acquire() as conn:
            result = await conn.fetchval("SELECT COUNT(*) FROM critique_episodes")
            return int(result or 0)


# ── Helpers ──────────────────────────────────────────────────────────────── #


def _parse_issues_from_document(document: str) -> list[str]:
    """Extract the bullet-point issues from a stored episode document string."""
    lines = document.split("\n")
    issues: list[str] = []
    in_issues = False
    for line in lines:
        if line.startswith("Issues:"):
            in_issues = True
            continue
        if in_issues and line.startswith("- "):
            issues.append(line[2:].strip())
    return issues
