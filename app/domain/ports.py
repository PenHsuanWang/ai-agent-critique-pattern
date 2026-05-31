"""Domain-level port (interface) definitions — zero external dependencies.

Defines the abstract contracts (Protocols) that infrastructure adapters must
satisfy.  Declaring them in the domain layer keeps the core free of concrete
implementation details:

  CheckpointerPort   — read/write OrchestratorState to any backing store.
  EpisodicMemoryPort — write/query episodic critique history in any vector store.

Usage in OrchestratorService::

    def set_checkpointer(self, store: CheckpointerPort) -> None: ...
    def set_episodic_memory(self, store: EpisodicMemoryPort) -> None: ...

Any class that implements the required async methods satisfies the Protocol
without explicit inheritance (structural subtyping / duck typing).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.domain.models import OrchestratorState


@runtime_checkable
class CheckpointerPort(Protocol):
    """Persistence contract for OrchestratorState snapshots.

    Both PostgreSQLOrchestratorStore and InMemoryOrchestratorStore satisfy
    this Protocol.  All methods are async so the Orchestrator can await them
    uniformly regardless of the underlying backend.
    """

    async def save(self, state: "OrchestratorState") -> None:
        """Persist (upsert) the current state snapshot."""
        ...

    async def get(self, session_id: str) -> "Optional[OrchestratorState]":
        """Return the state for *session_id*, or None if not found."""
        ...

    async def delete(self, session_id: str) -> None:
        """Remove the state record for *session_id*."""
        ...


@runtime_checkable
class EpisodicMemoryPort(Protocol):
    """Vector-store contract for episodic critique history.

    EpisodicMemoryStore (PostgreSQL + pgvector) satisfies this Protocol.
    Declared here so future adapters (e.g., Pinecone) can be swapped in
    without touching the Orchestrator.
    """

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
        """Persist a completed critique episode."""
        ...

    async def query_similar(
        self,
        query_text: str,
        n_results: int = 3,
        only_failed: bool = True,
    ) -> list[Any]:
        """Return the n most semantically similar historical episodes."""
        ...

    async def count(self) -> int:
        """Return the total number of stored episodes."""
        ...
