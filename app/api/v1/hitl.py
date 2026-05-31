"""HITL (Human-in-the-Loop) API endpoints.

GET  /api/v1/sessions/{session_id}/state   — inspect a (paused) session
POST /api/v1/sessions/{session_id}/resume  — approve or continue with human feedback
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from app.schemas.hitl import HITLResumeRequest, HITLSessionStateResponse
from app.services.orchestrator import orchestrator_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["hitl"])


def _state_to_response(state) -> HITLSessionStateResponse:
    cr = state.critique_result
    return HITLSessionStateResponse(
        session_id=state.session_id,
        status=state.status,
        iteration_count=state.iteration_count,
        max_iterations=state.max_iterations,
        enable_hitl=state.enable_hitl,
        current_draft=state.current_draft,
        critique_passed=cr.passed if cr else None,
        critique_issues=list(cr.issues) if cr else [],
        critique_revision_notes=cr.revision_notes if cr else "",
        critique_confidence=cr.confidence_score if cr else None,
        final_output=state.final_output,
        error_message=state.error_message,
    )


@router.get("/{session_id}/state", response_model=HITLSessionStateResponse)
async def get_session_state(
    session_id: Annotated[str, Path(description="Orchestrator session ID")],
):
    """Return the current state of an orchestration session.

    Useful for polling paused HITL sessions before deciding to approve or revise.
    """
    if orchestrator_service._checkpointer is None:
        raise HTTPException(
            status_code=503,
            detail="Checkpointer not configured. Set DATABASE_URL or use in-memory fallback.",
        )
    state = await orchestrator_service._checkpointer.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return _state_to_response(state)


@router.post("/{session_id}/resume", response_model=HITLSessionStateResponse)
async def resume_session(
    session_id: Annotated[str, Path(description="Orchestrator session ID")],
    body: HITLResumeRequest,
):
    """Resume a HITL-paused orchestration session.

    - ``action: "approve"`` — accept the current draft as the final output.
    - ``action: "revise"``  — run additional iterations with optional human feedback
                              injected as extra revision guidance for the Generator.
    """
    if orchestrator_service._checkpointer is None:
        raise HTTPException(
            status_code=503,
            detail="Checkpointer not configured. Set DATABASE_URL to enable HITL.",
        )

    state = await orchestrator_service._checkpointer.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    if state.status != "paused_for_hitl":
        raise HTTPException(
            status_code=409,
            detail=f"Session '{session_id}' is not paused for HITL (status='{state.status}').",
        )

    logger.info(
        "HITL resume | session='%s' | action='%s'", session_id, body.action
    )

    updated_state = await orchestrator_service.resume(
        state=state,
        action=body.action,
        human_feedback=body.human_feedback,
        additional_iterations=body.additional_iterations,
    )
    return _state_to_response(updated_state)
