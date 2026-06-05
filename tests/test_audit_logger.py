from app.domain.models import OrchestratorState, CritiqueResult
from app.services.audit_logger import generate_audit_log


def test_generate_audit_log_empty():
    state = OrchestratorState(
        session_id="test-session-empty",
        task="Test Task",
        max_iterations=3,
        enable_hitl=False,
    )
    
    log = generate_audit_log(state)
    
    assert "Audit Log for Session: test-session-empty" in log
    assert "**Final Status:** pending" in log
    assert "**Total Iterations:** 0" in log


def test_generate_audit_log_with_history():
    state = OrchestratorState(
        session_id="test-session-history",
        task="Test Task",
        max_iterations=3,
        enable_hitl=False,
    )
    
    state.iteration_count = 2
    state.status = "success"
    
    state.draft_history.append("This is draft 1.")
    cr1 = CritiqueResult(
        passed=False, 
        issues=["Missing details"], 
        revision_notes="Please add details.", 
        confidence_score=0.8
    )
    state.critique_history.append(cr1)
    
    state.draft_history.append("This is draft 2. It has details.")
    cr2 = CritiqueResult(
        passed=True, 
        issues=[], 
        revision_notes="", 
        confidence_score=0.95
    )
    state.critique_history.append(cr2)
    
    log = generate_audit_log(state)
    
    assert "Audit Log for Session: test-session-history" in log
    assert "**Final Status:** success" in log
    assert "**Total Iterations:** 2" in log
    
    assert "## Iteration 1" in log
    assert "```text\nThis is draft 1.\n```" in log
    assert "### Critique Assessment (Confidence: 0.80)" in log
    assert "**Passed:** False" in log
    assert "**Issues Found (1):**" in log
    assert "- Missing details" in log
    assert "**Revision Notes:**\nPlease add details." in log
    
    assert "## Iteration 2" in log
    assert "```text\nThis is draft 2. It has details.\n```" in log
    assert "### Critique Assessment (Confidence: 0.95)" in log
    assert "**Passed:** True" in log
    assert "- Missing details" in log # In iteration 1
    
def test_generate_audit_log_missing_critique():
    state = OrchestratorState(
        session_id="test-session-missing",
        task="Test Task",
        max_iterations=3,
        enable_hitl=False,
    )
    state.iteration_count = 1
    state.draft_history.append("This is a draft without critique")
    # No critique appended
    
    log = generate_audit_log(state)
    assert "## Iteration 1" in log
    assert "### Final Assessment" in log
    assert "Draft approved or loop terminated without further critique." in log