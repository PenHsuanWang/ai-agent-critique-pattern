"""Core configuration module.

Extends the MVP settings with critique-pattern-specific controls:
- Per-role token budgets (generator vs critique)
- Extended thinking toggle (deep reasoning for Generator)
- Orchestration parameters (max_iterations, enable_hitl)
- PostgreSQL checkpointer (optional — falls back to in-memory)
- Vector episodic memory via pgvector (optional, opt-in — requires DATABASE_URL)
"""

from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Anthropic credentials ────────────────────────────────────────────── #
    anthropic_api_key: SecretStr = Field(..., alias="ANTHROPIC_API_KEY")
    anthropic_base_url: Optional[str] = Field(None, alias="ANTHROPIC_BASE_URL")

    # ── Model ────────────────────────────────────────────────────────────── #
    claude_model: str = Field("claude-3-7-sonnet-20250219", alias="CLAUDE_MODEL")
    max_retries: int = Field(2, alias="MAX_RETRIES")

    # Per-role token budgets — Generator needs room for extended thinking.
    generator_max_tokens: int = Field(16000, alias="GENERATOR_MAX_TOKENS")
    critique_max_tokens: int = Field(8192, alias="CRITIQUE_MAX_TOKENS")

    # ── Extended thinking (Generator only) ───────────────────────────────── #
    extended_thinking: bool = Field(False, alias="EXTENDED_THINKING")
    thinking_budget_tokens: int = Field(10000, alias="THINKING_BUDGET_TOKENS")

    # ── Orchestration ────────────────────────────────────────────────────── #
    max_iterations: int = Field(3, alias="MAX_ITERATIONS")

    # Inner ReAct loop safety caps — prevent runaway tool-call spirals.
    # These limit the number of tool-call rounds within a single agent invocation,
    # independently of the outer orchestration iteration count.
    generator_max_tool_calls: int = Field(15, alias="GENERATOR_MAX_TOOL_CALLS")
    critique_max_tool_calls: int = Field(10, alias="CRITIQUE_MAX_TOOL_CALLS")

    # ── PostgreSQL Checkpointer ───────────────────────────────────────────── #
    # Set to a DSN like "postgresql://user:pass@localhost:5432/dbname".
    # Leave None to use the in-memory store (development / testing only).
    database_url: Optional[str] = Field(None, alias="DATABASE_URL")

    # ── Vector Episodic Memory (pgvector) ────────────────────────────────── #
    # Set to true to enable the Critique agent's historical pattern retrieval.
    # Requires DATABASE_URL — episodes are stored in the same PostgreSQL instance.
    # On first use, downloads the all-MiniLM-L6-v2 sentence-transformer (~90 MB).
    vector_memory_enabled: bool = Field(False, alias="VECTOR_MEMORY_ENABLED")

    # ── Application ──────────────────────────────────────────────────────── #
    app_env: str = Field("development", alias="APP_ENV")
    debug: bool = Field(False, alias="DEBUG")
    local_data_dir: str = Field("local_data", alias="LOCAL_DATA_DIR")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
