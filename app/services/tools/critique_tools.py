"""Critique-specific tool: submit_critique.

The ``submit_critique`` tool is the structured output mechanism for the Critique agent.
It MUST be called once to signal evaluation completion.

Design:
- The tool definition (JSON schema) is static and exported as SUBMIT_CRITIQUE_TOOL_DEF.
- The tool *implementation* is a closure created per-run via make_submit_critique_handler().
  This closure captures a mutable result holder, ensuring each CritiqueAgentService.run()
  invocation has its own isolated state — no global mutable singletons.
"""

import logging
from typing import Any

from app.domain.models import CritiqueResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────── #
# Tool schema                                                                    #
# ──────────────────────────────────────────────────────────────────────────── #

SUBMIT_CRITIQUE_TOOL_DEF: dict[str, Any] = {
    "name": "submit_critique",
    "description": (
        "Submit your final structured critique evaluation. "
        "You MUST call this tool exactly once after completing your analysis. "
        "This signals that your evaluation is finished and records the result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {
                "type": "boolean",
                "description": (
                    "True if the draft fully and accurately addresses the task "
                    "with no significant issues. False if the draft needs revision."
                ),
            },
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "A list of specific, concrete issues found in the draft. "
                    "Each item must identify a distinct problem (e.g., "
                    "'Missing citation for claim about X', 'Conclusion contradicts "
                    "premise in paragraph 3'). Empty list if passed=true."
                ),
            },
            "revision_notes": {
                "type": "string",
                "description": (
                    "Actionable, specific instructions for the Generator to fix the draft. "
                    "Must directly address every item in 'issues'. "
                    "Empty string if passed=true."
                ),
            },
            "confidence_score": {
                "type": "number",
                "description": (
                    "Your confidence in this evaluation, from 0.0 (very uncertain) "
                    "to 1.0 (absolutely certain). Reflects quality of evidence found."
                ),
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": ["passed", "issues", "revision_notes"],
    },
}


# ──────────────────────────────────────────────────────────────────────────── #
# Per-run closure factory                                                        #
# ──────────────────────────────────────────────────────────────────────────── #


def make_submit_critique_handler(
    result_holder: list[CritiqueResult],
) -> tuple[str, Any]:
    """Return a (tool_name, callable) pair bound to *result_holder*.

    ``result_holder`` is a single-element list used as a mutable container so
    the closure can write the result back to the caller's scope.

    Usage::

        holder: list[CritiqueResult] = []
        name, fn = make_submit_critique_handler(holder)
        # ... wire fn into the tool registry ...
        # After the critique loop: holder[0] is the CritiqueResult
    """

    def _handler(inp: dict[str, Any]) -> str:
        if result_holder:
            logger.warning("submit_critique called more than once — ignoring duplicate call.")
            return "Error: submit_critique has already been called. Do not call it again."

        try:
            result = CritiqueResult(
                passed=bool(inp["passed"]),
                issues=[str(i) for i in inp.get("issues", [])],
                revision_notes=str(inp.get("revision_notes", "")),
                confidence_score=float(inp.get("confidence_score", 1.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("submit_critique received malformed input: %s — %s", inp, exc)
            return f"Error: Malformed critique input — {exc}. Check the required fields."

        result_holder.append(result)
        logger.info(
            "Critique submitted | passed=%s | issues=%d | confidence=%.2f",
            result.passed,
            len(result.issues),
            result.confidence_score,
        )
        return (
            "Critique submitted successfully. "
            "You may now provide a brief closing summary if you wish, then finish."
        )

    return "submit_critique", _handler
