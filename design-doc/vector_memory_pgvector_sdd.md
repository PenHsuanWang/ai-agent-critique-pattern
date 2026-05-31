# Software Design Document (SDD): Vector Memory Refactoring to pgvector

## 1. Introduction

### 1.1 Purpose
This Software Design Document (SDD) details the architectural and technical specifications for refactoring the **Vector Episodic Memory** component of the `ai-agent-critique-pattern` project. The system is transitioning from a local ChromaDB implementation to **PostgreSQL using the `pgvector` extension** combined with local `sentence-transformers`.

### 1.2 Scope
This refactoring focuses strictly on the persistence layer of the Episodic Memory used by the Critique Agent. It involves modifying database dependencies, creating SQL schemas for vector storage, rewriting the `EpisodicMemoryStore` repository class, and implementing local text embedding generation. 

### 1.3 Background & Context
The system implements a Decoupled Multi-Agent State Machine Architecture (Generator–Critique pattern). The Vector Episodic Memory serves as the Critique Agent's long-term semantic memory, storing historical error patterns and reflections to prevent recurring failures and confirmation bias. Currently, this is powered by ChromaDB. Since the system already leverages PostgreSQL (via `asyncpg`) for Orchestrator state checkpointer persistence, moving vector storage to PostgreSQL unifies the infrastructure and reduces third-party dependencies.

---

## 2. System Architecture

### 2.1 Architectural Context
In the multi-tier memory architecture of the system:
1. **Working Memory:** Short-term `AgentSession` (ReAct traces).
2. **Session Memory:** Medium-term `OrchestratorState` (Checkpointer in Postgres).
3. **Long-term Semantic Memory (Episodic):** Persistent historical critique records (Currently ChromaDB, moving to Postgres + `pgvector`).

### 2.2 Component Flow
1. The **CritiqueAgent** uses the `retrieve_similar_critiques` tool.
2. The tool calls `EpisodicMemoryStore.query_similar()`.
3. `EpisodicMemoryStore` uses a local `SentenceTransformer` to encode the query into a 384-dimensional dense vector.
4. An async query is sent to PostgreSQL (`asyncpg`) using the `<=>` (cosine distance) operator.
5. The retrieved records are returned as `EpisodeRecord` dataclasses back to the ReAct loop.

---

## 3. Data Design

### 3.1 Database Schema
The vector memory will be persisted in a new PostgreSQL table `critique_episodes`.

```sql
-- Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Table Definition
CREATE TABLE IF NOT EXISTS critique_episodes (
    episode_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    passed BOOLEAN NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL,
    revision_notes TEXT,
    document TEXT NOT NULL,
    embedding vector(384) -- Dimension matches 'all-MiniLM-L6-v2'
);
```

### 3.2 Indexing Strategy
To optimize high-dimensional vector similarity search, an HNSW (Hierarchical Navigable Small World) index will be applied, optimized for Cosine Distance.

```sql
CREATE INDEX ON critique_episodes USING hnsw (embedding vector_cosine_ops);
```

### 3.3 Data Models
The existing `EpisodeRecord` domain model will remain unchanged to guarantee backward compatibility with the `retrieve_similar_critiques` tool.

---

## 4. Component Design: `EpisodicMemoryStore`

The `app/infrastructure/vector_memory.py` module will be completely rewritten.

### 4.1 Dependencies
- **`asyncpg`**: Asynchronous PostgreSQL driver (already in project).
- **`pgvector`**: Python library to register vector types with `asyncpg`.
- **`sentence-transformers`**: Generates local embeddings to avoid OpenAI/Anthropic API costs.

### 4.2 Class Structure

```python
from sentence_transformers import SentenceTransformer
import asyncpg
from pgvector.asyncpg import register_vector

class EpisodicMemoryStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        # Load local embedding model (synchronously on startup)
        self._encoder = SentenceTransformer('all-MiniLM-L6-v2')

    async def _setup(self):
        """Registers pgvector types on the asyncpg connection pool."""
        async with self._pool.acquire() as conn:
            await register_vector(conn)

    async def store_episode(self, session_id: str, iteration: int, task: str, issues: list[str], revision_notes: str, passed: bool, confidence_score: float) -> None:
        """Embeds document and executes INSERT."""
        # 1. Construct document
        # 2. Generate embedding: self._encoder.encode(document)
        # 3. asyncpg.execute("INSERT INTO critique_episodes ...")

    async def query_similar(self, query_text: str, n_results: int = 3, only_failed: bool = True) -> list[EpisodeRecord]:
        """Embeds query and executes SELECT with cosine distance."""
        # 1. Generate query_embedding
        # 2. asyncpg.fetch("SELECT *, embedding <=> $1 AS distance FROM critique_episodes WHERE passed = false ORDER BY distance LIMIT $2")
        # 3. Map rows to EpisodeRecord
```

### 4.3 Concurrency & Performance Considerations
The `sentence-transformers` model performs CPU-bound tensor operations. If generating embeddings blocks the `asyncio` event loop significantly during high concurrency, the `self._encoder.encode()` calls will be wrapped in `asyncio.get_running_loop().run_in_executor(None, ...)`.

---

## 5. Migration & Implementation Strategy

### 5.1 Step-by-Step Execution Plan
1. **Dependency Update:** Modify `pyproject.toml` (Drop `chromadb`, add `pgvector`, `sentence-transformers`). Sync with `uv`.
2. **Database Initialization:** Add the SQL schema creation logic to the application startup lifespan (`app/main.py`), ensuring `CREATE EXTENSION` and table creation execute before any Agent tasks run.
3. **Module Refactoring:** Replace the `chromadb` implementation in `app/infrastructure/vector_memory.py` with the `asyncpg` + `SentenceTransformer` implementation.
4. **Service Wiring:** Update `app/main.py` where `EpisodicMemoryStore` is initialized to pass the PostgreSQL `asyncpg.Pool` instead of the local directory path.

### 5.2 Rollback Plan
- The legacy `./vector_memory` folder (ChromaDB artifacts) will remain untouched during the deployment.
- If severe issues occur, the system can be rolled back to the previous Git commit. Since the public interface (`store_episode`, `query_similar`) is strictly preserved, no changes outside of `vector_memory.py` and `main.py` will require reversion.
