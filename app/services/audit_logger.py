import logging

from app.domain.models import OrchestratorState

logger = logging.getLogger(__name__)


def generate_audit_log(state: OrchestratorState) -> str:
    """Generates a Markdown formatted audit log from the OrchestratorState."""
    log = [f"# Audit Log for Session: {state.session_id}"]
    log.append(f"**Final Status:** {state.status}")
    log.append(f"**Total Iterations:** {state.iteration_count}\n")

    # The length of draft_history will be state.iteration_count
    for i, draft in enumerate(state.draft_history):
        log.append(f"## Iteration {i+1}")

        # Generator's contribution
        log.append("### Generator Output")
        log.append(f"```text\n{draft}\n```\n")

        # Critique's contribution (if available for this iteration)
        if i < len(state.critique_history):
            critique = state.critique_history[i]
            log.append(
                f"### Critique Assessment (Confidence: {critique.confidence_score:.2f})"
            )
            log.append(f"**Passed:** {critique.passed}")

            if critique.issues:
                log.append(f"**Issues Found ({len(critique.issues)}):**")
                for issue in critique.issues:
                    log.append(f"- {issue}")

            if critique.revision_notes:
                log.append(f"**Revision Notes:**\n{critique.revision_notes}")
        else:
            # Usually happens on the final approved iteration if we don't store the final critique
            log.append("### Final Assessment")
            log.append("Draft approved or loop terminated without further critique.")

        log.append("---\n")

    return "\n".join(log)
