"""Conditional edge routing functions for LangGraph workflow."""

import logging
from typing import Literal
from app.graph.state import InvestigationState

logger = logging.getLogger(__name__)


def route_from_supervisor(
    state: InvestigationState,
) -> Literal["log_analyst", "rag_retrieval", "end"]:
    """
    Route from supervisor based on plan and execution budget:
    - If budget exhausted or error -> 'end'
    - If specialists needed -> 'log_analyst'
    - If evidence collected -> 'rag_retrieval'
    """
    status = state.get("workflow_status")
    if status in ("BUDGET_EXHAUSTED", "FAILED"):
        return "end"

    next_step = state.get("next_step")
    if next_step == "dispatch_specialists":
        return "log_analyst"
    elif next_step == "synthesize_report":
        return "rag_retrieval"
    elif next_step == "end":
        return "end"

    # Default fallback
    return "end"


def route_after_log_analyst(
    state: InvestigationState,
) -> Literal["change_analyst", "rag_retrieval"]:
    """
    Route after Log Analyst execution:
    - If Change Analyst not yet executed, proceed to 'change_analyst'
    - If already completed, proceed to 'rag_retrieval'
    """
    completed = state.get("completed_agents", [])
    if "ChangeAnalyst" not in completed and state.get("change_result") is None:
        return "change_analyst"
    return "rag_retrieval"
