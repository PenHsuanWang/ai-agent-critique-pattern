"""POST /api/v1/critique — Generator–Critique orchestration endpoint.

Responsibilities:
1. Deserialise the CritiqueRequest.
2. Build an OrchestratorState from the request.
3. Delegate to OrchestratorService.
4. Serialise and return CritiqueResponse (with HITL review_url when applicable).

All orchestration logic lives in OrchestratorService — this handler stays thin.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request

from app.domain.exceptions import AgentError, OrchestratorError
from app.domain.models import OrchestratorState
from app.schemas.critique import CritiqueRequest, CritiqueResponse, CritiqueResultSchema
from app.services.orchestrator import orchestrator_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_review_url(http_request: Optional[Request], session_id: str) -> Optional[str]:
    """Build the HITL resume URL based on the incoming request's base URL."""
    if http_request is None:
        return None
    base = str(http_request.base_url).rstrip("/")
    return f"{base}/api/v1/sessions/{session_id}/resume"


@router.post(
    "/critique",
    response_model=CritiqueResponse,
    summary="Run the Generator–Critique loop on a task",
    description=(
        "Submit a task to the multi-agent Generator–Critique system. "
        "The Generator will research and produce a draft; the Critique agent will "
        "evaluate it and provide structured feedback. The loop repeats until the "
        "draft is approved or the iteration cap is reached. "
        "Set enable_hitl=true to pause instead of returning a best-effort draft."
    ),
)
async def critique(request: CritiqueRequest, http_request: Request) -> CritiqueResponse:
    logger.info(
        "Critique request | session='%s' | max_iterations=%d | hitl=%s | task='%.80s...'",
        request.session_id,
        request.max_iterations,
        request.enable_hitl,
        request.task,
    )

    state = OrchestratorState(
        session_id=request.session_id,
        task=request.task,
        max_iterations=request.max_iterations,
        enable_hitl=request.enable_hitl,
    )

    try:
        state = await orchestrator_service.run(state)

        logger.info(
            "Critique completed | session='%s' | status=%s | iterations=%d",
            request.session_id,
            state.status,
            state.iteration_count,
        )

        review_url = None
        if state.status == "paused_for_hitl":
            review_url = _build_review_url(http_request, state.session_id)

        return CritiqueResponse(
            session_id=state.session_id,
            final_output=state.final_output,
            iterations_used=state.iteration_count,
            status=state.status,
            critique_history=[
                CritiqueResultSchema(**cr.to_dict()) for cr in state.critique_history
            ],
            draft_history=list(state.draft_history),
            review_url=review_url,
        )

    except OrchestratorError as exc:
        logger.error(
            "Orchestrator error for session '%s': %s", request.session_id, exc
        )
        return CritiqueResponse(
            session_id=state.session_id,
            final_output=state.current_draft or "The agent system encountered an error.",
            iterations_used=state.iteration_count,
            status="error",
            critique_history=[
                CritiqueResultSchema(**cr.to_dict()) for cr in state.critique_history
            ],
            draft_history=list(state.draft_history),
        )

    except AgentError as exc:
        logger.warning("Agent error for session '%s': %s", request.session_id, exc)
        return CritiqueResponse(
            session_id=request.session_id,
            final_output="The agent system encountered a domain error.",
            iterations_used=state.iteration_count,
            status="error",
            critique_history=[],
            draft_history=[],
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Unhandled error for session '%s': %s",
            request.session_id,
            exc,
            exc_info=True,
        )
        return CritiqueResponse(
            session_id=request.session_id,
            final_output="An unexpected internal error occurred. Please try again.",
            iterations_used=state.iteration_count,
            status="error",
            critique_history=[],
            draft_history=[],
        )

