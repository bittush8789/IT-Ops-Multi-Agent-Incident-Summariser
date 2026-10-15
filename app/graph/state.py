"""Typed shared state definition for the LangGraph investigation workflow."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from app.schemas.agent_findings import (
    ChangeAnalystResult,
    HistoricalIncidentMatch,
    LogAnalystResult,
)
from app.schemas.report import IncidentReportBase


class InvestigationState(TypedDict, total=False):
    """
    Shared typed state flowing across all nodes in the LangGraph workflow.
    Ensures strict type-safety, auditability, and immutability where needed.
    """

    # Incident Core Metadata
    incident_id: int
    incident_key: str
    title: str
    description: str
    service_name: str
    severity: str
    started_at: Optional[datetime]
    resolved_at: Optional[datetime]

    # Integration Configuration Overrides
    log_source_path: Optional[str]
    github_repo: Optional[str]
    trace_id: Optional[str]

    # Budget & Execution Tracking
    step_count: int
    max_steps: int
    retry_counts: Dict[str, int]

    # Planning & Supervision
    investigation_plan: Optional[str]
    supervisor_notes: Optional[str]
    next_step: Optional[str]

    # Specialist Findings
    completed_agents: List[str]
    failed_agents: List[str]
    agent_errors: Dict[str, str]
    log_result: Optional[LogAnalystResult]
    change_result: Optional[ChangeAnalystResult]

    # Historical Context (pgvector RAG)
    historical_matches: List[HistoricalIncidentMatch]

    # Final Output & Workflow Status
    final_report: Optional[IncidentReportBase]
    workflow_status: str  # PENDING, IN_PROGRESS, COMPLETED, PARTIAL, BUDGET_EXHAUSTED, FAILED
