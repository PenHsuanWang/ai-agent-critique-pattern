"""GeneratorAgentService — ReAct loop for the Generator role.

Responsibilities:
- Receive a task + optional revision context from the Orchestrator.
- Run a full ReAct (Reason + Act) loop using Claude until end_turn.
- Return only the final text response as the candidate draft.

Memory isolation:
- Operates on a private AgentSession supplied by the Orchestrator.
- Never exposes its internal message history to the Critique agent.
- Extended thinking blocks (if enabled) stay inside this session and are
  never forwarded across the isolation boundary.
"""

import logging
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from app.core.config import settings
from app.domain.exceptions import GeneratorLoopError
from app.domain.models import AgentSession
from app.services.agent_utils import call_handler, extract_text, serialize_content
from app.services.tools.common_tools import (
    COMMON_TOOL_DEFINITIONS,
    COMMON_TOOL_REGISTRY,
)

logger = logging.getLogger(__name__)

_GENERATOR_SYSTEM_PROMPT = """\
You are a Generator Agent in a multi-agent system.

Your role is to produce a comprehensive, well-researched, and accurate response \
to the user's task. You have access to tools to search and read local documents. \
Use them thoroughly to gather all relevant information before producing your answer.

Guidelines:
- Be thorough: read all documents that are relevant to the task.
- Be structured: organise your response with clear sections where appropriate.
- Be precise: do not make claims you cannot support with the available documents.
- Be complete: ensure your response fully addresses every aspect of the task.

CRITICAL OUTPUT RULE — this is non-negotiable:
Your final response MUST contain ONLY the pure draft text itself.
Do NOT include any conversational preamble, meta-commentary, or wrappers such as:
  - "Here is the updated draft:"
  - "I have revised Section 2 to address the feedback..."
  - "Based on the critique, I have made the following changes..."
  - "Here is my response:"
Begin writing the draft content immediately — no introduction, no explanation of \
what you changed. The Critique Agent evaluates the draft text only; any \
conversational prefix will be treated as part of the draft and will cause rejection.\
"""


def _extract_text(message: Message) -> str:
    return extract_text(message)


def _serialize_content(content: Any) -> Any:
    return serialize_content(content)


class GeneratorAgentService:
    """Drives the Generator ReAct loop for a single orchestration iteration."""

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
        revision_context: str = "",
        previous_draft: str = "",
    ) -> str:
        """Run the Generator loop and return the final candidate draft.

        Args:
            session: A fresh, isolated AgentSession (must not be shared).
            task: The original user task description.
            revision_context: Structured feedback from the previous Critique
                iteration (issues + revision notes). Empty on first iteration.
            previous_draft: The Generator's own draft from the previous iteration.
                Injected into the prompt so the Generator knows what it is
                revising rather than rewriting from scratch (prevents "Amnesia").
                Empty on first iteration.

        Returns:
            The final text draft produced by Claude.

        Raises:
            GeneratorLoopError: If the loop exceeds the safety cap or ends
                                in an unexpected state.
        """
        # Build the initial user message combining task + revision guidance.
        initial_message = self._build_initial_message(task, revision_context, previous_draft)
        session.add_user_message(initial_message)

        max_tool_calls = settings.generator_max_tool_calls
        for iteration in range(max_tool_calls):
            logger.debug(
                "Generator loop iteration %d for session '%s'",
                iteration,
                session.agent_id,
            )

            create_kwargs: dict[str, Any] = {
                "model": settings.claude_model,
                "max_tokens": settings.generator_max_tokens,
                "system": _GENERATOR_SYSTEM_PROMPT,
                "tools": COMMON_TOOL_DEFINITIONS,
                "messages": session.messages,
            }

            # Extended thinking — give the Generator deep reasoning capacity.
            if settings.extended_thinking:
                create_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": settings.thinking_budget_tokens,
                }

            response: Message = await self._client.messages.create(**create_kwargs)

            logger.debug("Generator stop_reason=%s", response.stop_reason)

            # ── Case 1: Final answer ──────────────────────────────────────── #
            if response.stop_reason == "end_turn":
                final_text = _extract_text(response)
                session.add_assistant_message(_serialize_content(response.content))
                if not final_text.strip():
                    raise GeneratorLoopError(
                        "Generator produced an empty draft. Cannot proceed."
                    )
                logger.info(
                    "Generator produced draft (%d chars) for session '%s'",
                    len(final_text),
                    session.agent_id,
                )
                return final_text

            # ── Case 2: Tool call(s) requested ───────────────────────────── #
            if response.stop_reason == "tool_use":
                session.add_assistant_message(_serialize_content(response.content))

                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(
                            "Generator executing tool '%s' | session='%s'",
                            block.name,
                            session.agent_id,
                        )
                        handler = COMMON_TOOL_REGISTRY.get(block.name)
                        if handler is None:
                            result = (
                                f"Error: Unknown tool '{block.name}'. "
                                f"Available: {list(COMMON_TOOL_REGISTRY)}"
                            )
                        else:
                            try:
                                result = await call_handler(handler, dict(block.input))
                            except Exception as exc:
                                logger.error(
                                    "Generator tool '%s' raised unexpected exception: %s",
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

                session.add_tool_results(tool_results)
                continue

            # ── Unexpected stop_reason ────────────────────────────────────── #
            logger.warning(
                "Generator: unexpected stop_reason '%s'", response.stop_reason
            )
            raise GeneratorLoopError(
                f"Generator loop ended with unexpected stop_reason '{response.stop_reason}'."
            )

        raise GeneratorLoopError(
            f"Generator tool-call loop exceeded the safety cap of {max_tool_calls} rounds "
            "without producing a final draft. The task may be too complex or the agent "
            "is stuck in a tool-use cycle. Consider increasing GENERATOR_MAX_TOOL_CALLS."
        )

    @staticmethod
    def _build_initial_message(task: str, revision_context: str, previous_draft: str = "") -> str:
        """Compose the Generator's initial user message.

        FIRST ITERATION (revision_context is empty):
          Returns a plain task prompt. No previous draft, no revision notes.

        SUBSEQUENT ITERATIONS (revision_context is non-empty):
          Returns a structured prompt that includes:
            1. Original task — re-injected every time to prevent scope drift.
            2. YOUR PREVIOUS DRAFT — the Generator's own prior output, so it
               revises its existing work rather than rewriting from scratch.
               This resolves the "Generator Amnesia / Brain Split" problem:
               without the previous draft the Generator has no context for
               what it is fixing and produces a completely different document
               each iteration, making the loop chaotic and unresolvable.
               Safe to pass across the isolation boundary — it is the
               Generator's own text, not any Critique internals.
            3. REVISION REQUIRED — structured issues + notes from CritiqueResult.
               These are the ONLY Critique outputs that reach the Generator.
               The Critique's internal reasoning, tool calls, and intermediate
               thoughts are NEVER included here.
            4. Source amnesia warning — explicit instruction to re-read source
               documents via tools rather than guessing. This prevents the LLM
               from hallucinating details (e.g., a corrected date) to satisfy
               the Critique without actually looking up the ground truth.
        """
        if not revision_context:
            # Iteration 1 — simple task prompt.
            return f"Please complete the following task:\n\n{task}"

        return (
            f"Please complete the following task:\n\n{task}\n\n"
            "━━━ YOUR PREVIOUS DRAFT ━━━\n"
            f"{previous_draft}\n"
            "━━━ END OF PREVIOUS DRAFT ━━━\n\n"
            "━━━ REVISION REQUIRED ━━━\n"
            "Your previous draft was reviewed and did not meet quality standards.\n"
            "Address ALL of the following issues before producing your new draft:\n\n"
            f"{revision_context}\n"
            "━━━ END OF REVISION NOTES ━━━\n\n"
            "IMPORTANT: You are in a fresh session. Your memory of previously read documents has been cleared.\n"
            "If you need to add or verify factual details to address these issues, you MUST use your tools to "
            "re-read the source documents. Do not guess or hallucinate details.\n\n"
            "Produce an improved draft that fully resolves the issues listed above."
        )


# Module-level singleton.
generator_agent_service = GeneratorAgentService()
