"""FastAPI application entry point.

Responsibilities:
- Create and configure the FastAPI application instance.
- Register all routers (critique, documents, HITL).
- Configure structured logging.
- Initialise infrastructure (PostgreSQL pool, vector memory) during lifespan.
- Expose a /health endpoint for liveness probes.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.critique import router as critique_router
from app.api.v1.documents import router as documents_router
from app.api.v1.hitl import router as hitl_router
from app.core.config import settings


def _configure_logging() -> None:
    log_level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        stream=sys.stdout,
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _configure_logging()
    logger = logging.getLogger(__name__)
    logger.info(
        "Starting AI Agent Critique Pattern | env=%s | model=%s | "
        "max_iterations=%d | extended_thinking=%s | hitl_db=%s | vector_memory=%s",
        settings.app_env,
        settings.claude_model,
        settings.max_iterations,
        settings.extended_thinking,
        bool(settings.database_url),
        settings.vector_memory_enabled,
    )

    from app.infrastructure.database import close_pool, get_pool, init_pool  # noqa: PLC0415
    from app.infrastructure.checkpointer import get_store  # noqa: PLC0415
    from app.services.orchestrator import orchestrator_service  # noqa: PLC0415

    # ── PostgreSQL checkpointer ──────────────────────────────────────────── #
    if settings.database_url:
        await init_pool(settings.database_url)
    pool = get_pool()
    checkpointer = get_store(pool)
    orchestrator_service.set_checkpointer(checkpointer)

    # ── Vector episodic memory ───────────────────────────────────────────── #
    if settings.vector_memory_enabled:
        if pool is None:
            logger.warning(
                "VECTOR_MEMORY_ENABLED=true but DATABASE_URL is not set. "
                "pgvector episodic memory requires PostgreSQL — skipping."
            )
        else:
            try:
                from app.infrastructure.vector_memory import EpisodicMemoryStore  # noqa: PLC0415

                episodic_store = EpisodicMemoryStore(pool)
                await episodic_store._setup()
                orchestrator_service.set_episodic_memory(episodic_store)
            except Exception as exc:
                logger.error(
                    "Failed to initialise vector episodic memory: %s. "
                    "Critique agent will run without historical context.",
                    exc,
                )

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────── #
    await close_pool()
    logger.info("Shutting down AI Agent Critique Pattern.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Agent — Generator–Critique Pattern",
        description=(
            "Multi-agent system with a Generator ReAct loop and a Critique ReAct loop "
            "that antagonistically refine outputs through structured feedback cycles. "
            "Supports PostgreSQL checkpointing, HITL pause/resume, and vector episodic memory."
        ),
        version="0.6.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(critique_router, prefix="/api/v1", tags=["critique"])
    app.include_router(documents_router, prefix="/api/v1/documents", tags=["documents"])
    app.include_router(hitl_router)  # prefix defined in router: /api/v1/sessions

    @app.get("/health", tags=["ops"], summary="Liveness probe")
    async def health():
        from app.infrastructure.database import get_pool as _get_pool  # noqa: PLC0415

        return {
            "status": "ok",
            "env": settings.app_env,
            "model": settings.claude_model,
            "extended_thinking": settings.extended_thinking,
            "max_iterations": settings.max_iterations,
            "checkpointer": "postgresql" if _get_pool() else "in-memory",
            "vector_memory": settings.vector_memory_enabled,
        }

    return app


app = create_app()
