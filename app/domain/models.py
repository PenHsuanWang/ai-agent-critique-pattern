"""Core domain entities — zero external dependencies (Clean Architecture).

Models:
  AgentSession      — private ReAct conversation state for a single agent instance.
  CritiqueResult    — structured output produced by the Critique agent.
  OrchestratorState — parent-level state governing the Generator↔Critique loop.

Memory isolation contract
─────────────────────────
AgentSession instances are NEVER shared across agents or iterations.
The only data that crosses the memory isolation boundary is:
  • Generator  → OrchestratorState.current_draft  (plain string)
  • Critique   → OrchestratorState.critique_result (CritiqueResult value object)
All internal ReAct traces stay inside the agent's private AgentSession.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSession:
    """Private ReAct conversation state for a single agent instance.

    ``messages`` follows the Anthropic API format:
      [{"role": "user" | "assistant", "content": str | list[ContentBlock]}, ...]

    A new AgentSession must be instantiated for every agent invocation —
    never reuse or share instances across agent roles or loop iterations.
    """

    agent_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: Any) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, tool_results: list[dict[str, Any]]) -> None:
        """Wrap tool results in a ``user`` turn as required by the Anthropic API."""
        self.messages.append({"role": "user", "content": tool_results})


@dataclass
class CritiqueResult:
    """Structured evaluation produced by the Critique agent.

    This is the sole output crossing from the Critique agent to the Orchestrator.
    All internal reasoning that produced this result stays inside the Critique's
    private AgentSession and is never visible to the Generator.
    """

    passed: bool
    issues: list[str] = field(default_factory=list)
    revision_notes: str = ""
    confidence_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "revision_notes": self.revision_notes,
            "confidence_score": self.confidence_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CritiqueResult:
        return cls(
            passed=bool(data["passed"]),
            issues=list(data.get("issues", [])),
            revision_notes=str(data.get("revision_notes", "")),
            confidence_score=float(data.get("confidence_score", 1.0)),
        )


@dataclass
class OrchestratorState:
    """Parent-level state for the Generator–Critique orchestration loop.

    This is the ONLY medium through which the two agents exchange information.
    All fields crossing the isolation boundary are strictly typed and structured —
    no raw ReAct traces, no internal message histories, no object references.

    Loop lifecycle
    ──────────────
    status: pending → running → success | max_iterations_reached | paused_for_hitl | error
    """

    session_id: str
    task: str
    max_iterations: int = 3
    enable_hitl: bool = False  # If True, pause for human review when max_iterations reached

    # ── Loop control ─────────────────────────────────────────────────────── #
    iteration_count: int = 0
    status: str = "pending"  # pending|running|success|max_iterations_reached|paused_for_hitl|error

    # ── Cross-boundary exchange (the only shared data) ───────────────────── #
    current_draft: str = ""
    critique_result: CritiqueResult | None = None

    # ── Audit trail (archived, never fed back into agent contexts) ────────── #
    draft_history: list[str] = field(default_factory=list)
    critique_history: list[CritiqueResult] = field(default_factory=list)

    # ── Final output ─────────────────────────────────────────────────────── #
    final_output: str = ""
    error_message: str = ""

    # ── Serialisation ────────────────────────────────────────────────────── #

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain JSON-compatible dict for persistence."""
        return {
            "session_id": self.session_id,
            "task": self.task,
            "max_iterations": self.max_iterations,
            "enable_hitl": self.enable_hitl,
            "iteration_count": self.iteration_count,
            "status": self.status,
            "current_draft": self.current_draft,
            "critique_result": self.critique_result.to_dict() if self.critique_result else None,
            "draft_history": list(self.draft_history),
            "critique_history": [cr.to_dict() for cr in self.critique_history],
            "final_output": self.final_output,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestratorState:
        """Deserialise from a plain dict (e.g., loaded from PostgreSQL JSONB)."""
        state = cls(
            session_id=data["session_id"],
            task=data["task"],
            max_iterations=data["max_iterations"],
            enable_hitl=data.get("enable_hitl", False),
        )
        state.iteration_count = data.get("iteration_count", 0)
        state.status = data.get("status", "pending")
        state.current_draft = data.get("current_draft", "")
        cr = data.get("critique_result")
        state.critique_result = CritiqueResult.from_dict(cr) if cr else None
        state.draft_history = list(data.get("draft_history", []))
        state.critique_history = [
            CritiqueResult.from_dict(c) for c in data.get("critique_history", [])
        ]
        state.final_output = data.get("final_output", "")
        state.error_message = data.get("error_message", "")
        return state
