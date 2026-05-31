"""Pydantic request/response schemas for the critique orchestration API."""

from pydantic import BaseModel, Field


class CritiqueResultSchema(BaseModel):
    """Serialised form of a single CritiqueResult produced during the loop."""

    passed: bool = Field(..., description="True if the draft met quality standards.")
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems identified in the draft.",
    )
    revision_notes: str = Field(
        default="",
        description="Actionable instructions for the Generator to fix the draft.",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Critique agent's confidence in the evaluation (0–1).",
    )


class CritiqueRequest(BaseModel):
    session_id: str = Field(
        ...,
        description=(
            "Unique task identifier. Used for logging and state tracking. "
            "Each new task should have a unique ID."
        ),
        examples=["task-analysis-001"],
    )
    task: str = Field(
        ...,
        min_length=1,
        max_length=32768,
        description="The task or question the Generator must address and the Critique must evaluate.",
        examples=["Write a comprehensive summary of all documents in the knowledge base."],
    )
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Maximum number of Generator↔Critique cycles before returning the best draft. "
            "The loop exits early if the Critique approves the draft."
        ),
    )
    enable_hitl: bool = Field(
        default=False,
        description=(
            "If True and max_iterations is reached without approval, pause the session "
            "instead of returning the best-effort draft. Requires DATABASE_URL to be set."
        ),
    )


class CritiqueResponse(BaseModel):
    session_id: str = Field(..., description="Echo of the request session_id.")
    final_output: str = Field(
        ...,
        description=(
            "The final approved draft (if status=success) or the best draft "
            "produced before hitting the iteration cap (if status=max_iterations_reached). "
            "Empty when status=paused_for_hitl."
        ),
    )
    iterations_used: int = Field(
        ...,
        description="Number of Generator↔Critique cycles that were executed.",
    )
    status: str = Field(
        ...,
        description=(
            "'success' — Critique approved the output. "
            "'max_iterations_reached' — cap hit; best draft returned. "
            "'paused_for_hitl' — paused awaiting human review (use HITL resume endpoint). "
            "'error' — an unexpected failure occurred."
        ),
    )
    critique_history: list[CritiqueResultSchema] = Field(
        default_factory=list,
        description="Ordered list of CritiqueResult objects from each iteration.",
    )
    draft_history: list[str] = Field(
        default_factory=list,
        description="Ordered list of drafts produced by the Generator in each iteration.",
    )
    review_url: str | None = Field(
        default=None,
        description=(
            "URL for the HITL review endpoint when status=paused_for_hitl. "
            "POST to this URL with a HITLResumeRequest to approve or continue."
        ),
    )
