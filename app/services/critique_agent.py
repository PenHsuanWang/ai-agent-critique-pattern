"""CritiqueAgentService — ReAct loop for the Critique role.

Responsibilities:
- Receive the original task and a clean candidate draft from the Orchestrator.
- Run a full ReAct loop using Claude to gather evidence and evaluate the draft.
- Mandate the use of the ``submit_critique`` tool to produce a structured result.
- Return a CritiqueResult — the ONLY output that crosses the isolation boundary.

Memory isolation:
- Operates on a private AgentSession supplied by the Orchestrator.
- Internal reasoning, tool call history, and intermediate thoughts are NEVER
  forwarded to the Generator or included in the parent OrchestratorState.
- The submit_critique handler is a per-run closure — no global mutable state.
"""

import asyncio
import logging
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from app.core.config import settings
from app.domain.exceptions import CritiqueLoopError
from app.domain.models import AgentSession, CritiqueResult
from app.services.agent_utils import call_handler, extract_text, serialize_content
from app.services.tools.common_tools import (
    COMMON_TOOL_DEFINITIONS,
    COMMON_TOOL_REGISTRY,
)
from app.services.tools.critique_tools import (
    SUBMIT_CRITIQUE_TOOL_DEF,
    make_submit_critique_handler,
)

logger = logging.getLogger(__name__)

_CRITIQUE_SYSTEM_PROMPT = """\
You are a Critique Agent in a multi-agent system.

Your role is to rigorously and objectively evaluate the quality of a draft \
produced by a Generator Agent. You are the quality gate — the draft only passes \
if it fully, accurately, and completely addresses the original task.

Your evaluation process:
1. Read the original task carefully to understand the full requirements.
2. Read the draft and identify all potential weaknesses.
3. Use the available document tools to verify factual claims and find supporting \
   or contradicting evidence.
4. Form a well-reasoned judgment based on evidence, not assumption.

Criteria for rejection (set passed=false if ANY of these apply):
- Factual inaccuracies or unsubstantiated claims
- Missing information that is clearly relevant and available in the documents
- Logical inconsistencies or contradictions
- Incomplete coverage of the task requirements
- Poor structure that makes the response difficult to understand

SCOPE BOUNDARY — evaluate ONLY the substance of the draft against the task:
Do NOT penalise the draft for:
- The absence or presence of a title or section headers (unless the task requires them)
- Meta-commentary introduced by YOU during evaluation
- Formatting style choices that do not affect clarity or completeness

You MUST call the ``submit_critique`` tool exactly once to record your final \
evaluation. This is mandatory — do not end without calling it.\
"""


def _extract_text(message: Message) -> str:
    return extract_text(message)


def _serialize_content(content: Any) -> Any:
    return serialize_content(content)


class CritiqueAgentService:
    """Drives the Critique ReAct loop for a single orchestration iteration."""

    def __init__(self, client: AsyncAnthropic | None = None) -> None:
        self._client = client or AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=settings.anthropic_base_url,
            max_retries=settings.max_retries,
        )

    async def run(
        self,
        session: AgentSession,
        task: str,
        draft: str,
        previous_critique: CritiqueResult | None = None,
        extra_tool_defs: list[dict] | None = None,
        extra_tool_registry: dict[str, Any] | None = None,
    ) -> CritiqueResult:
        """Run the Critique loop and return a structured CritiqueResult.

        Each call MUST receive a freshly constructed AgentSession — never reuse
        a session across iterations or across agents. This is the primary mechanism
        that prevents Context Pollution (the Critique never sees the Generator's
        ReAct traces, intermediate reasoning, or tool call history).

        What crosses the isolation boundary INTO this loop:
          - task:             the original user task (same string as Generator receives)
          - draft:            the Generator's final plain-text output ONLY — no reasoning
          - previous_critique: the Critique's own prior structured result (issues list
                               only). This resolves "Critique Amnesia" — without it the
                               Critic evaluates the revised draft from scratch and may
                               forget it asked for specific changes, leading to endless
                               loops or contradictory feedback.

        What crosses the boundary OUT of this loop:
          - CritiqueResult: a typed dataclass (passed, issues, revision_notes,
                            confidence_score). Nothing else. Internal ReAct traces,
                            tool results, and reasoning are discarded by the caller.

        Args:
            session: A fresh, isolated AgentSession (must not be shared).
            task: The original user task (same as given to the Generator).
            draft: The clean final draft from the Generator (no ReAct traces).
            previous_critique: The CritiqueResult from the PREVIOUS iteration, if any.
                Injected as a PREVIOUS EVALUATION CONTEXT block so the Critique can
                verify whether the Generator resolved its prior issues. None on the
                first iteration (no prior critique exists). Safe to pass across the
                isolation boundary — it is the Critique's own structured output, not
                any Generator internals.
            extra_tool_defs: Optional additional Anthropic tool definitions to inject
                             (e.g., retrieve_similar_critiques from episodic memory).
            extra_tool_registry: Callable registry for extra_tool_defs entries.
                                 Values may be sync or async callables.

        Returns:
            A CritiqueResult with passed, issues, revision_notes, confidence_score.

        Raises:
            CritiqueLoopError: If the loop ends without calling submit_critique,
                               or if it exceeds the safety cap.
        """
        # Per-run closure — result_holder is fresh per call; zero global mutable state.
        # The duplicate-call guard inside make_submit_critique_handler prevents the
        # agent from overwriting its own evaluation if it calls submit_critique twice.
        result_holder: list[CritiqueResult] = []
        submit_name, submit_handler = make_submit_critique_handler(result_holder)

        # Tool registry assembly order matters:
        #   1. Common document tools (shared with Generator)
        #   2. Extra tools injected by the Orchestrator (e.g., episodic memory)
        #   3. submit_critique — ALWAYS last; it is the mandatory exit tool
        # submit_critique overrides any same-named tool in extra_tool_registry (should
        # never happen in practice, but the ordering makes the invariant explicit).
        all_tool_defs = COMMON_TOOL_DEFINITIONS + (extra_tool_defs or []) + [SUBMIT_CRITIQUE_TOOL_DEF]
        tool_registry = {
            **COMMON_TOOL_REGISTRY,
            **(extra_tool_registry or {}),
            submit_name: submit_handler,
        }

        # Build the evaluation prompt. previous_critique injects the PREVIOUS EVALUATION
        # CONTEXT block only when there are prior issues to verify. On iteration 1
        # (previous_critique=None) and when the previous critique passed with no issues,
        # the block is omitted — the Critique evaluates the draft fresh.
        initial_message = self._build_evaluation_request(task, draft, previous_critique)
        session.add_user_message(initial_message)

        for iteration in range(settings.critique_max_tool_calls):
            logger.debug(
                "Critique loop iteration %d for session '%s'",
                iteration,
                session.agent_id,
            )

            response: Message = await self._client.messages.create(
                model=settings.claude_model,
                max_tokens=settings.critique_max_tokens,
                system=_CRITIQUE_SYSTEM_PROMPT,
                tools=all_tool_defs,
                messages=session.messages,
            )

            logger.debug("Critique stop_reason=%s", response.stop_reason)

            # ── Case 1: Natural completion ───────────────────────────────── #
            # end_turn is acceptable ONLY if submit_critique was already called
            # earlier in this same loop. If the agent ends without submitting,
            # we raise — a missing structured result is unrecoverable.
            if response.stop_reason == "end_turn":
                session.add_assistant_message(_serialize_content(response.content))
                if result_holder:
                    return result_holder[0]
                # Critique ended without calling submit_critique — unacceptable.
                raise CritiqueLoopError(
                    "Critique agent reached end_turn without calling submit_critique. "
                    "Structured evaluation result is missing."
                )

            # ── Case 2: Tool call(s) requested ───────────────────────────── #
            if response.stop_reason == "tool_use":
                session.add_assistant_message(_serialize_content(response.content))

                tool_results: list[dict[str, Any]] = []
                # submit_was_called tracks whether submit_critique fired THIS round.
                # The loop exits immediately after, so the Critique cannot call other
                # tools after submitting — this preserves the exit-on-submit invariant.
                submit_was_called = False

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    logger.info(
                        "Critique executing tool '%s' | session='%s'",
                        block.name,
                        session.agent_id,
                    )
                    handler = tool_registry.get(block.name)
                    if handler is None:
                        # Return an error string to Claude instead of crashing —
                        # the agent can recover by choosing a different tool.
                        result = (
                            f"Error: Unknown tool '{block.name}'. "
                            f"Available: {list(tool_registry)}"
                        )
                    else:
                        try:
                            result = await call_handler(handler, dict(block.input))
                        except Exception as exc:
                            # A crashing tool must not kill the loop. Return the error
                            # as a tool result so Claude can handle or report it.
                            logger.error(
                                "Critique tool '%s' raised unexpected exception: %s",
                                block.name, exc, exc_info=True,
                            )
                            result = f"Error: Tool '{block.name}' encountered an unexpected error — {exc}"

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

                    if block.name == submit_name and result_holder:
                        submit_was_called = True

                session.add_tool_results(tool_results)

                # Exit immediately once submit_critique fires — do NOT wait for
                # end_turn. This guarantees we capture the structured result even
                # if Claude continues generating text after calling the tool.
                if submit_was_called:
                    logger.info(
                        "Critique completed submission for session '%s'",
                        session.agent_id,
                    )
                    return result_holder[0]

                continue

            # ── Unexpected stop_reason ────────────────────────────────────── #
            logger.warning(
                "Critique: unexpected stop_reason '%s'", response.stop_reason
            )
            raise CritiqueLoopError(
                f"Critique loop ended with unexpected stop_reason '{response.stop_reason}'."
            )

        raise CritiqueLoopError(
            f"Critique tool-call loop exceeded the safety cap of "
            f"{settings.critique_max_tool_calls} rounds without submitting a critique. "
            "The task may be too complex or the agent is stuck in a tool-use cycle. "
            "Consider increasing CRITIQUE_MAX_TOOL_CALLS."
        )

    @staticmethod
    def _build_evaluation_request(task: str, draft: str, previous_critique: CritiqueResult | None = None) -> str:
        """Build the Critique agent's evaluation prompt.

        ISOLATION INVARIANT — this method enforces the memory boundary at the
        message level:
          - Only the original task and the clean plain-text draft are included.
          - Generator ReAct traces, tool call history, and reasoning are NEVER
            included here. The Orchestrator strips all of that before calling run().

        PREVIOUS EVALUATION CONTEXT (Critique Amnesia fix):
          - When previous_critique is provided and has issues, the Critique receives
            a structured reminder of what it asked for in the prior iteration.
          - This prevents "Critique Amnesia": without it, a fresh AgentSession would
            cause the Critic to re-evaluate the draft without knowing what it
            previously requested, potentially rejecting changes it asked for or
            ignoring unresolved issues.
          - Only previous_critique.issues are injected — NOT revision_notes or
            confidence_score. Issues are the minimal signal needed to verify
            resolution; they do not expose any Generator internals.
          - If previous_critique.passed=True (e.g., HITL revise path) the issues
            list is empty, so the block is skipped — correct behaviour.
        """
        # Task block — always present, always first. Re-injecting the original
        # task on every iteration is what prevents scope creep: the Critique is
        # structurally forced to evaluate against the root objective, not just the
        # diff from the previous iteration.
        prompt = (
            "Please evaluate the following draft against the original task.\n\n"
            "━━━ ORIGINAL TASK ━━━\n"
            f"{task}\n"
            "━━━ END OF TASK ━━━\n\n"
        )

        # PREVIOUS EVALUATION CONTEXT — injected only when there are prior issues
        # to verify. Gives the Critique logical continuity without polluting it
        # with Generator internals or its own previous ReAct trace.
        if previous_critique and previous_critique.issues:
            issues_text = "\n".join(f"- {issue}" for issue in previous_critique.issues)
            prompt += (
                "━━━ PREVIOUS EVALUATION CONTEXT ━━━\n"
                "In the previous iteration, you evaluated an earlier version of this draft "
                "and identified the following issues that needed to be fixed:\n"
                f"{issues_text}\n\n"
                "Please verify if the Generator has successfully resolved these specific issues, "
                "in addition to checking for any new or remaining problems.\n"
                "━━━ END OF PREVIOUS EVALUATION CONTEXT ━━━\n\n"
            )

        # Draft block — always last. The Critique evaluates ONLY this text against
        # the task above. No Generator reasoning or tool calls are visible here.
        prompt += (
            "━━━ GENERATOR'S DRAFT (for your evaluation) ━━━\n"
            f"{draft}\n"
            "━━━ END OF DRAFT ━━━\n\n"
            "Analyse the draft thoroughly. Use available document tools to verify "
            "factual claims. When you have completed your evaluation, call "
            "``submit_critique`` with your structured assessment."
        )
        return prompt


# Module-level singleton.
critique_agent_service = CritiqueAgentService()
