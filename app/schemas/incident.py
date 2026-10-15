"""Pydantic schemas for incident management and API contracts."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class IncidentSeverity(str, Enum):
    """Incident severity classification."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    """Incident lifecycle status."""
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class InvestigationExecutionStatus(str, Enum):
    """Investigation execution progress status."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


# Incident Base, Create, Response
class IncidentBase(BaseModel):
    """Shared fields for incident representation."""
    title: str = Field(..., min_length=3, max_length=255, description="Brief summary of the incident")
    description: str = Field(..., min_length=5, description="Detailed problem statement")
    service_name: str = Field(..., min_length=2, max_length=100, description="Affected primary service or component")
    severity: IncidentSeverity = Field(default=IncidentSeverity.HIGH, description="Incident impact tier")
    status: IncidentStatus = Field(default=IncidentStatus.OPEN, description="Incident operational status")
    started_at: Optional[datetime] = Field(default=None, description="Timestamp when incident symptoms began")
    resolved_at: Optional[datetime] = Field(default=None, description="Timestamp when incident was mitigated or resolved")


class IncidentCreate(IncidentBase):
    """Schema for creating a new incident."""
    incident_key: Optional[str] = Field(default=None, description="Unique human-readable identifier (e.g. INC-2026-1001)")


class IncidentUpdate(BaseModel):
    """Schema for updating an existing incident."""
    title: Optional[str] = None
    description: Optional[str] = None
    service_name: Optional[str] = None
    severity: Optional[IncidentSeverity] = None
    status: Optional[IncidentStatus] = None
    started_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class IncidentResponse(IncidentBase):
    """Schema for incident output."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_key: str
    created_at: datetime
    updated_at: datetime


class PaginatedIncidentsResponse(BaseModel):
    """Paginated incident list wrapper."""
    items: List[IncidentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# Incident Events
class IncidentEventCreate(BaseModel):
    """Schema for recording an incident event or timeline marker."""
    incident_id: int
    event_type: str = Field(..., description="Type of event, e.g. ALERT, DEPLOYMENT, LOG_ANOMALY, STATUS_CHANGE")
    source: str = Field(..., description="System or agent emitting the event, e.g. LogAnalyst, GitHub, Monitoring")
    description: str = Field(..., description="Human-readable event narrative")
    event_timestamp: datetime = Field(..., description="Timestamp of the event occurrence")
    evidence_reference: Optional[str] = Field(default=None, description="Pointer to log line, commit hash, or trace")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Structured key-value context")


class IncidentEventResponse(IncidentEventCreate):
    """Schema for incident event output."""
    model_config = ConfigDict(from_attributes=True)

    id: int


# Agent Run Audit
class AgentRunResponse(BaseModel):
    """Audit record for individual agent executions."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    agent_name: str
    status: str
    steps_used: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    token_usage: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Investigation Request & Status
class InvestigationRequest(BaseModel):
    """Parameters to trigger or scope an automated investigation."""
    max_steps: Optional[int] = Field(default=None, description="Override maximum step budget for LangGraph")
    log_source_path: Optional[str] = Field(default=None, description="Optional custom path to log fixture or stream")
    github_repo: Optional[str] = Field(default=None, description="Optional repository override for change analysis")
    force_refresh: bool = Field(default=False, description="Re-run investigation even if existing results are present")


class InvestigationStatusResponse(BaseModel):
    """Investigation status, progress metrics, and collected findings summary."""
    incident_id: int
    incident_key: str
    status: InvestigationExecutionStatus
    steps_used: int
    max_steps: int
    completed_agents: List[str]
    failed_agents: List[str]
    has_report: bool
    summary_message: str
    agent_runs: List[AgentRunResponse] = Field(default_factory=list)
