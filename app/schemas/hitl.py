"""HITL (Human-in-the-Loop) API schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class HITLResumeRequest(BaseModel):
    """Request body for resuming a paused HITL session."""

    action: Literal["approve", "revise"] = Field(
        ...,
        description=(
            "'approve' — accept the current draft as final output. "
            "'revise' — continue the loop with optional human feedback."
        ),
    )
    human_feedback: str = Field(
        "",
        description="Optional human reviewer notes injected as additional revision guidance.",
    )
    additional_iterations: int = Field(
        1,
        ge=1,
        le=10,
        description="How many more Generator–Critique iterations to run when action='revise'.",
    )


class HITLSessionStateResponse(BaseModel):
    """Current state of an orchestration session."""

    session_id: str
    status: str
    iteration_count: int
    max_iterations: int
    enable_hitl: bool
    current_draft: str
    critique_passed: Optional[bool] = None
    critique_issues: list[str] = []
    critique_revision_notes: str = ""
    critique_confidence: Optional[float] = None
    final_output: str = ""
    error_message: str = ""
