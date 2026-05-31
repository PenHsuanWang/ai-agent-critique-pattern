"""Typed domain error hierarchy.

Inner layers raise these typed errors; the Presentation layer catches and
maps them to appropriate HTTP responses.  Never expose raw stack traces.
"""


class AgentError(Exception):
    """Base error for all agent domain failures."""


class ToolSecurityError(AgentError):
    """A tool call violated path-traversal security constraints."""


class ToolExecutionError(AgentError):
    """A tool failed during execution (non-recoverable at service level)."""


class SessionNotFoundError(AgentError):
    """Requested session_id does not exist in the store."""


class AgentLoopError(AgentError):
    """A ReAct agent loop terminated in an unexpected state."""


class GeneratorLoopError(AgentLoopError):
    """The Generator agent loop failed to produce a draft."""


class CritiqueLoopError(AgentLoopError):
    """The Critique agent loop failed to submit a structured critique."""


class OrchestratorError(AgentError):
    """The Orchestrator encountered an unrecoverable error managing the loop."""
