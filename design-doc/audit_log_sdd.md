# Software Design Document (SDD): Deterministic Observer (Audit Log)

## 1. Introduction & Scope
- **Purpose:** The purpose of this feature is to provide a transparent, deterministic, and cost-free audit log of the interactions between the Generator and Critique agents throughout an orchestration session. It addresses the need for tracking the evolution of the draft and the specific issues raised during the iterative process without introducing a third, hallucination-prone, and latency-inducing AI agent.
- **System Boundaries:** 
  - **In-Scope:** Extracting structured data (`draft_history`, `critique_history`) from the `OrchestratorState` upon session completion (success, max iterations, or error) and formatting it into a human-readable Markdown string.
  - **Out-of-Scope:** Deploying an additional AI model to summarize or interpret the logs, modifying the existing state machine's core logic, or altering how the Generator and Critique agents operate.
- **Stakeholders:** Developers, System Administrators, and End-Users (for auditing and debugging).

## 2. System Architecture (HLD)
- **Deployment Strategy:** Local / API Server (No change to existing deployment).
- **High-Level Diagram (Conceptual):**
  The Orchestrator acts as the "All-Knowing Observer" by default. A new utility function or method on the `OrchestratorService` extracts data from the completed `OrchestratorState` to produce the audit log.
  
  `[Orchestrator Loop] -> (Completes) -> [OrchestratorState] -> [generate_audit_log(state)] -> [Markdown Audit Log]`
- **External Dependencies:** None. Relies purely on internal state management.

## 3. Domain-Driven Design (DDD) Mapping
- **Bounded Contexts:** `Orchestration / Session Management`
- **Aggregates & Entities:** `OrchestratorState` (Aggregate Root), `CritiqueResult` (Value Object).
- **Domain Events:** `SessionCompleted` (Triggers generation of the audit log, currently implicit via API response handling).

## 4. Component Design (LLD)
- **Microservices / Modules:** 
  - Module: `app/services/orchestrator.py` or a dedicated reporting utility `app/services/audit_logger.py`.
- **API Contracts:** 
  - Ensure the `generate_audit_log(state: OrchestratorState) -> str` function is available.
  - *Optionally* expose an API endpoint (e.g., `GET /api/v1/sessions/{session_id}/audit-log`) to retrieve the formatted log, or include it in the existing `CritiqueResponse`.
- **Design Patterns:**
  - **Adapter/Formatter Pattern:** Transforming the internal state object into a specific string format (Markdown).

## 5. Data Design
- **Logical Schema:** The data already exists within `OrchestratorState` (`draft_history` and `critique_history`). No new database tables are required.
- **Storage Solutions:** No persistent storage changes. The audit log can be generated on-the-fly from the `OrchestratorState` fetched via the `CheckpointerPort`.
- **Data Flow:**
  1. Loop completes.
  2. The final `OrchestratorState` is accessed.
  3. `generate_audit_log` maps `draft_history`[i] and `critique_history`[i] to a Markdown string.

## 6. UI & Interaction Design
- **Key User Journeys:** A developer or user calls the API and receives a clean Markdown representation of the agent interactions.
- **State Management:** Fully stateless generation function.

## 7. Technical Specifications & Non-Functional Requirements
- **Performance:** O(N) where N is the number of iterations. Zero external API calls. Near-zero latency impact.
- **Security:** Standard API security. Audit logs contain drafts and critiques, so authorization must match the existing session viewing permissions.
- **Scalability & Reliability:** Highly scalable as it involves simple string manipulation. 100% deterministic reliability.

## 8. Implementation Plan

### Step 1: Implement the Generator Function
Create the pure Python function to generate the audit log.
**File:** `app/services/audit_logger.py` (New file) or add to `app/services/orchestrator.py`.

```python
from app.domain.models import OrchestratorState

def generate_audit_log(state: OrchestratorState) -> str:
    """Generates a Markdown formatted audit log from the OrchestratorState."""
    log = [f"# Audit Log for Session: {state.session_id}"]
    log.append(f"**Final Status:** {state.status}")
    log.append(f"**Total Iterations:** {state.iteration_count}\\n")
    
    # Critique history size might be 1 less than draft history if loop ended successfully
    for i, draft in enumerate(state.draft_history):
        log.append(f"## Iteration {i+1}")
        
        # Generator's contribution
        log.append("### Generator Output")
        log.append(f"```text\\n{draft}\\n```\\n")
        
        # Critique's contribution (if available for this iteration)
        if i < len(state.critique_history):
            critique = state.critique_history[i]
            log.append(f"### Critique Assessment (Confidence: {critique.confidence_score:.2f})")
            log.append(f"**Passed:** {critique.passed}")
            
            if critique.issues:
                log.append(f"**Issues Found ({len(critique.issues)}):**")
                for issue in critique.issues:
                    log.append(f"- {issue}")
            
            if critique.revision_notes:
                log.append(f"**Revision Notes:**\\n{critique.revision_notes}")
        else:
            # Usually happens on the final approved iteration if we don't store the final critique
            log.append("### Final Assessment")
            log.append("Draft approved or loop terminated without further critique.")
            
        log.append("---\\n")
        
    return "\\n".join(log)
```

### Step 2: Integrate into API (Optional)
Decide if the audit log should be returned in the `POST /api/v1/critique` response or exposed via a new `GET` endpoint.

**Option A (New Endpoint):** Add `GET /api/v1/sessions/{session_id}/audit` to `app/api/v1/hitl.py` or `critique.py`.

### Step 3: Write Unit Tests
Test the `generate_audit_log` function with mock `OrchestratorState` objects ensuring Markdown formatting is correct for various scenarios (e.g., failed immediately, passed on first try, hit max iterations).