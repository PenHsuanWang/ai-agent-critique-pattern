"""Episodic memory tool for the Critique agent.

Provides a closure factory (same pattern as ``make_submit_critique_handler``)
so the Critique agent can search historical critique episodes at runtime.

Usage
─────
    name, handler = make_retrieve_critiques_handler(episodic_store)
    # Register alongside submit_critique and common tools in CritiqueAgentService.

Tool contract
─────────────
Input  : {"query": str, "n_results": int (optional, default 3)}
Output : formatted string listing similar historical episodes with their issues
         and revision notes — designed for direct insertion into LLM context.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.infrastructure.vector_memory import EpisodicMemoryStore

logger = logging.getLogger(__name__)

# ── Tool definition (Anthropic tool-use schema) ───────────────────────────── #

RETRIEVE_CRITIQUES_TOOL_DEF: dict = {
    "name": "retrieve_similar_critiques",
    "description": (
        "Search the episodic memory for historically similar critique sessions. "
        "Returns past issues, revision notes, and whether the draft passed. "
        "Use this BEFORE writing your critique to surface recurring failure patterns "
        "and avoid confirmation bias. Query with a short description of the current task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Short description of the current task or the draft's main topic.",
            },
            "n_results": {
                "type": "integer",
                "description": "Maximum number of similar episodes to retrieve (default: 3, max: 10).",
                "default": 3,
            },
        },
        "required": ["query"],
    },
}


# ── Closure factory ───────────────────────────────────────────────────────── #


def make_retrieve_critiques_handler(
    store: "EpisodicMemoryStore",
) -> tuple[str, Callable]:
    """Return a (tool_name, async_handler) pair bound to the given memory store.

    The returned handler is async so it integrates naturally with the Critique
    agent's async ReAct loop without blocking the event loop.
    """

    async def _handler(query: str, n_results: int = 3) -> str:
        n_results = max(1, min(n_results, 10))  # clamp to [1, 10]
        try:
            episodes = await store.query_similar(
                query_text=query,
                n_results=n_results,
                only_failed=True,  # focus on failure patterns
            )
        except Exception as exc:
            logger.warning("Episodic retrieval error: %s", exc)
            return f"[retrieve_similar_critiques] Error during retrieval: {exc}"

        if not episodes:
            return (
                "[retrieve_similar_critiques] No similar historical episodes found. "
                "This appears to be a novel task type."
            )

        lines = [f"Found {len(episodes)} similar historical critique(s):\n"]
        for i, ep in enumerate(episodes, start=1):
            status = "PASSED" if ep.passed else "FAILED"
            similarity_pct = round((1.0 - ep.distance) * 100, 1)
            lines.append(
                f"--- Episode {i} (similarity: {similarity_pct}%, outcome: {status}) ---"
            )
            lines.append(f"Session: {ep.session_id}, Iteration: {ep.iteration}")
            if ep.issues:
                lines.append("Issues identified:")
                for issue in ep.issues:
                    lines.append(f"  • {issue}")
            if ep.revision_notes:
                lines.append(f"Revision notes: {ep.revision_notes}")
            lines.append("")

        return "\n".join(lines)

    return RETRIEVE_CRITIQUES_TOOL_DEF["name"], _handler


# ── Orchestrator convenience factory ─────────────────────────────────────── #


def build_tool_pair(
    store: "EpisodicMemoryStore",
) -> tuple[list[dict], dict]:
    """Return the (tool_defs, tool_registry) pair for a given memory store.

    Called by OrchestratorService before each Critique run so the Critique
    agent can retrieve historically similar episodes.  Keeping this factory
    here ensures that all episodic-memory tool assembly logic lives in one
    module rather than being split between the tools module and the
    orchestrator.

    Returns:
        A 2-tuple of (list[tool_definition_dict], {name: handler}).
        Both entries are empty when *store* is None — but callers should
        check for None before calling this function.
    """
    name, handler = make_retrieve_critiques_handler(store)
    return [RETRIEVE_CRITIQUES_TOOL_DEF], {name: handler}
