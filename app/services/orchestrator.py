"""OrchestratorService — parent controller for the Generator–Critique loop.

Architecture overview
─────────────────────
The Orchestrator is the ONLY component that knows about both agents.
It enforces the memory isolation contract by acting as a strict state filter:

  1. Generator Phase
     - Creates a fresh AgentSession for the Generator.
     - Passes only: original task + structured revision notes from last critique.
     - Captures only: the final plain-text draft.
     - Discards: all internal Generator ReAct traces.

  2. Critique Phase
     - Creates a fresh AgentSession for the Critique agent.
     - Passes only: original task + the clean final draft.
     - Captures only: the structured CritiqueResult.
     - Discards: all internal Critique ReAct traces.

  3. Loop control
     - Continues until CritiqueResult.passed == True OR max_iterations reached.
     - HITL: if enable_hitl=True and max_iterations reached, pauses instead of
       returning the best-effort draft. The session is checkpointed with
       status="paused_for_hitl" and can be resumed via the HITL API.
     - On any agent failure: propagates as OrchestratorError.

  4. Persistence
     - After every iteration (Generator + Critique), the state is checkpointed
       via the injected checkpointer (PostgreSQL or in-memory fallback).

  5. Episodic Memory
     - After each Critique run, the episode is stored in vector memory.
     - Before each Critique run, the retrieve_similar_critiques tool is injected
       if an episodic memory store is available.

Memory isolation is enforced at the Python object level:
- AgentSession instances are freshly constructed each iteration (no reuse).
- Data crossing the boundary is plain strings or dataclass value objects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from app.domain.exceptions import AgentLoopError, OrchestratorError
from app.domain.models import AgentSession, OrchestratorState
from app.domain.ports import CheckpointerPort, EpisodicMemoryPort
from app.services.critique_agent import CritiqueAgentService
from app.services.generator_agent import GeneratorAgentService
from app.services.tools.episodic_memory_tools import build_tool_pair

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class OrchestratorService:
    """Manages the full Generator↔Critique antagonistic loop."""

    def __init__(
        self,
        generator: GeneratorAgentService | None = None,
        critique: CritiqueAgentService | None = None,
    ) -> None:
        self._generator = generator or GeneratorAgentService()
        self._critique = critique or CritiqueAgentService()
        self._checkpointer: Optional[CheckpointerPort] = None
        self._episodic_memory: Optional[EpisodicMemoryPort] = None

    # ── Dependency injection setters (called from main.py lifespan) ────────── #

    def set_checkpointer(self, store: CheckpointerPort) -> None:
        """Inject the persistence store (PostgreSQL or in-memory)."""
        self._checkpointer = store
        logger.info("Orchestrator checkpointer set: %s", type(store).__name__)

    def set_episodic_memory(self, store: EpisodicMemoryPort) -> None:
        """Inject the vector episodic memory store."""
        self._episodic_memory = store
        logger.info("Orchestrator episodic memory set: %s", type(store).__name__)

    # ── Main loop ─────────────────────────────────────────────────────────── #

    async def run(self, state: OrchestratorState) -> OrchestratorState:
        """Execute the full Generator–Critique loop.

        Args:
            state: An OrchestratorState initialised with session_id, task, and
                   max_iterations. All other fields will be mutated in place.

        Returns:
            The updated OrchestratorState with final_output and status set.

        Raises:
            OrchestratorError: If an unrecoverable error occurs in either agent.
        """
        state.status = "running"
        logger.info(
            "Orchestrator starting | session='%s' | max_iterations=%d | hitl=%s",
            state.session_id,
            state.max_iterations,
            state.enable_hitl,
        )

        while state.iteration_count < state.max_iterations:
            state.iteration_count += 1
            logger.info(
                "Orchestrator iteration %d/%d | session='%s'",
                state.iteration_count,
                state.max_iterations,
                state.session_id,
            )

            # ── Generator Phase ───────────────────────────────────────────── #
            # A brand-new AgentSession is created every iteration.
            # This is the primary mechanism that prevents Context Pollution:
            # the Generator cannot see any Critique reasoning, tool calls, or
            # prior Generator traces from previous iterations. The session holds
            # only what the Orchestrator explicitly injects below.
            gen_session = AgentSession(
                agent_id=f"generator-{state.session_id}-iter{state.iteration_count}"
            )
            # _build_revision_context is the State Filter: it extracts ONLY the
            # structured issues and revision_notes from the last CritiqueResult.
            # The Critique's internal reasoning is discarded here.
            revision_context = self._build_revision_context(state)
            # Provide the previous draft on revision iterations so the Generator
            # knows what it is fixing rather than rewriting from scratch.
            # On iteration 1, state.current_draft is "" — no prior draft exists.
            # This is the Generator Amnesia fix: without the previous draft the
            # Generator has no anchor and will produce a completely new document,
            # making the loop chaotic.
            previous_draft = state.current_draft  # empty string on iter 1

            try:
                draft = await self._generator.run(
                    session=gen_session,
                    task=state.task,
                    revision_context=revision_context,
                    previous_draft=previous_draft,
                )
            except AgentLoopError as exc:
                logger.error(
                    "Generator failed on iteration %d for session '%s': %s",
                    state.iteration_count,
                    state.session_id,
                    exc,
                )
                state.status = "error"
                state.error_message = f"Generator failed: {exc}"
                await self._checkpoint(state)
                raise OrchestratorError(state.error_message) from exc

            # State filter: only the clean text draft crosses the boundary.
            # Generator ReAct traces, thinking blocks, and tool results stay
            # inside gen_session and are garbage-collected here.
            state.current_draft = draft
            state.draft_history.append(draft)
            logger.info(
                "Generator produced draft (%d chars) | session='%s' iter=%d",
                len(draft),
                state.session_id,
                state.iteration_count,
            )

            # ── Critique Phase ────────────────────────────────────────────── #
            # Same isolation pattern as the Generator: fresh AgentSession means
            # the Critique starts with zero memory of previous iterations or of
            # the Generator's internal work. It sees ONLY what the Orchestrator
            # passes below.
            crit_session = AgentSession(
                agent_id=f"critique-{state.session_id}-iter{state.iteration_count}"
            )

            # Inject episodic memory retrieval tool when available.
            extra_tool_defs, extra_tool_registry = self._build_episodic_tools()

            try:
                critique_result = await self._critique.run(
                    session=crit_session,
                    task=state.task,          # original task — always the root anchor
                    draft=draft,              # clean Generator output — no ReAct traces
                    # Pass the Critique's own previous result (Critique Amnesia fix).
                    # state.critique_result is None on iteration 1 (no prior critique).
                    # On iteration 2+, the Critique sees which issues it raised before
                    # so it can verify whether the Generator resolved them, preventing
                    # an endless loop where the Critic forgets what it asked for.
                    # SAFE: this is the Critique's own structured output — not any
                    # Generator internals. It contains issues (list[str]) only.
                    previous_critique=state.critique_result,
                    extra_tool_defs=extra_tool_defs,
                    extra_tool_registry=extra_tool_registry,
                )
            except AgentLoopError as exc:
                logger.error(
                    "Critique failed on iteration %d for session '%s': %s",
                    state.iteration_count,
                    state.session_id,
                    exc,
                )
                state.status = "error"
                state.error_message = f"Critique failed: {exc}"
                await self._checkpoint(state)
                raise OrchestratorError(state.error_message) from exc

            # State filter: only the structured CritiqueResult crosses the boundary.
            # The Critique's internal ReAct traces, tool results, and intermediate
            # reasoning are discarded. crit_session is now eligible for GC.
            state.critique_result = critique_result
            state.critique_history.append(critique_result)
            logger.info(
                "Critique result | passed=%s | issues=%d | confidence=%.2f | session='%s' iter=%d",
                critique_result.passed,
                len(critique_result.issues),
                critique_result.confidence_score,
                state.session_id,
                state.iteration_count,
            )

            # Store critique episode in vector memory for future sessions.
            await self._store_episode(state, critique_result)

            # Checkpoint after each full iteration.
            await self._checkpoint(state)

            # ── Loop control ─────────────────────────────────────────────── #
            if critique_result.passed:
                state.final_output = draft
                state.status = "success"
                logger.info(
                    "Orchestrator completed successfully on iteration %d | session='%s'",
                    state.iteration_count,
                    state.session_id,
                )
                await self._checkpoint(state)
                return state

            logger.info(
                "Draft rejected — will re-generate | session='%s' iter=%d",
                state.session_id,
                state.iteration_count,
            )

        # ── Max iterations reached ────────────────────────────────────────── #
        if state.enable_hitl:
            # Pause for human review instead of returning the best-effort draft.
            state.status = "paused_for_hitl"
            logger.info(
                "Orchestrator pausing for HITL review | session='%s'",
                state.session_id,
            )
            await self._checkpoint(state)
            return state

        state.final_output = state.current_draft
        state.status = "max_iterations_reached"
        logger.warning(
            "Orchestrator hit max_iterations=%d without approval | session='%s'",
            state.max_iterations,
            state.session_id,
        )
        await self._checkpoint(state)
        return state

    # ── HITL resume ───────────────────────────────────────────────────────── #

    async def resume(
        self,
        state: OrchestratorState,
        action: str,
        human_feedback: str = "",
        additional_iterations: int = 1,
    ) -> OrchestratorState:
        """Resume a HITL-paused session.

        Args:
            state: The paused OrchestratorState loaded from the checkpointer.
            action: "approve" — accept the current draft as final output.
                    "revise"  — extend the loop with human feedback injected
                                as an additional revision note.
            human_feedback: Human review notes (used when action="revise").
            additional_iterations: How many more iterations to allow (action="revise").

        Returns:
            Updated OrchestratorState after resume logic completes.
        """
        if state.status != "paused_for_hitl":
            raise OrchestratorError(
                f"Session '{state.session_id}' is not paused for HITL (status={state.status})."
            )

        if action == "approve":
            state.final_output = state.current_draft
            state.status = "success"
            logger.info(
                "HITL approved draft for session '%s'", state.session_id
            )
            await self._checkpoint(state)
            return state

        if action == "revise":
            # Inject human feedback as an extra revision note on the current critique.
            if state.critique_result and human_feedback:
                existing = state.critique_result.revision_notes
                state.critique_result.revision_notes = (
                    f"{existing}\n\n[Human reviewer]: {human_feedback}".strip()
                )
            state.max_iterations = state.iteration_count + additional_iterations
            state.status = "running"
            logger.info(
                "HITL extending loop by %d iteration(s) for session '%s'",
                additional_iterations,
                state.session_id,
            )
            return await self.run(state)

        raise OrchestratorError(f"Unknown HITL action '{action}'. Expected 'approve' or 'revise'.")

    # ── Private helpers ───────────────────────────────────────────────────── #

    async def _checkpoint(self, state: OrchestratorState) -> None:
        """Persist state snapshot (no-op if checkpointer not configured)."""
        if self._checkpointer is None:
            return
        try:
            await self._checkpointer.save(state)
        except Exception as exc:
            logger.warning("Checkpoint save failed for session '%s': %s", state.session_id, exc)

    async def _store_episode(self, state: OrchestratorState, critique_result: Any) -> None:
        """Store critique episode in vector memory (no-op if not configured)."""
        if self._episodic_memory is None:
            return
        try:
            await self._episodic_memory.store_episode(
                session_id=state.session_id,
                iteration=state.iteration_count,
                task=state.task,
                issues=list(critique_result.issues),
                revision_notes=critique_result.revision_notes,
                passed=critique_result.passed,
                confidence_score=critique_result.confidence_score,
            )
        except Exception as exc:
            logger.warning(
                "Episodic memory store failed for session '%s' iter=%d: %s",
                state.session_id,
                state.iteration_count,
                exc,
            )

    def _build_episodic_tools(self) -> tuple[list[dict], dict]:
        """Return episodic-memory tool defs and registry, or empty structures.

        Delegates to build_tool_pair() in episodic_memory_tools so that all
        tool-assembly logic stays in one place.  Returns empty structures when
        episodic memory is not configured so the Critique agent runs normally.
        """
        if self._episodic_memory is None:
            return [], {}
        return build_tool_pair(self._episodic_memory)

    @staticmethod
    def _build_revision_context(state: OrchestratorState) -> str:
        """Extract structured revision feedback for the Generator.

        Memory isolation guarantee: ONLY the issues list and revision_notes
        from the CritiqueResult are forwarded. The Critique agent's internal
        ReAct traces, tool calls, and reasoning never reach the Generator.
        """
        if state.critique_result is None:
            return ""  # First iteration — no prior critique.

        cr = state.critique_result
        if not cr.issues and not cr.revision_notes:
            return ""

        issues_text = "\n".join(f"  {i+1}. {issue}" for i, issue in enumerate(cr.issues))
        lines = [f"Issues identified by the Critique Agent (iteration {state.iteration_count - 1}):"]
        if issues_text:
            lines.append(issues_text)
        if cr.revision_notes:
            lines.append(f"\nRevision instructions:\n  {cr.revision_notes}")
        if cr.confidence_score < 1.0:
            lines.append(f"\n(Critique confidence: {cr.confidence_score:.0%})")

        return "\n".join(lines)


# Module-level singleton.
orchestrator_service = OrchestratorService()
