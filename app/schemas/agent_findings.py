"""Structured schemas for agent findings and specialist outputs."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LogFindingItem(BaseModel):
    """An individual log-derived finding with concrete evidence."""
    timestamp: datetime = Field(..., description="Timestamp of the log entry")
    service: str = Field(..., description="Service emitting the log")
    error_type: str = Field(..., description="Classification: HTTP_5XX, EXCEPTION, TIMEOUT, RESOURCE_EXHAUSTION")
    message: str = Field(..., description="Log message or exception string")
    http_status: Optional[int] = Field(default=None, description="HTTP status code if present")
    exception_class: Optional[str] = Field(default=None, description="Class name of exception if present")
    count: int = Field(default=1, description="Occurrences of this exact pattern")
    evidence_reference: str = Field(..., description="Log source pointer, file name, line number, or trace ID")
    is_fact: bool = Field(default=True, description="True for observed facts, False for inferences")


class ErrorGroup(BaseModel):
    """Grouped recurring errors by service, category, and time window."""
    service: str
    error_type: str
    sample_message: str
    total_occurrences: int
    first_seen: datetime
    last_seen: datetime
    affected_endpoints: List[str] = Field(default_factory=list)


class LogAnalystResult(BaseModel):
    """Complete structured output from Log Analyst Agent."""
    status: str = Field(default="COMPLETED", description="COMPLETED, FAILED, or PARTIAL")
    earliest_error_timestamp: Optional[datetime] = None
    subsequent_symptoms: List[str] = Field(default_factory=list)
    error_groups: List[ErrorGroup] = Field(default_factory=list)
    findings: List[LogFindingItem] = Field(default_factory=list)
    raw_log_count: int = 0
    errors_detected: int = 0
    inferred_root_cause_notes: Optional[str] = None
    error_message: Optional[str] = None


class ChangeItem(BaseModel):
    """Individual commit or deployment record."""
    commit_id: str = Field(..., description="Git commit SHA or deployment identifier")
    author: str = Field(..., description="Author or deployer identity")
    message: str = Field(..., description="Commit message or release title")
    timestamp: datetime = Field(..., description="Timestamp of change deployment or merge")
    repository: str = Field(..., description="Repository full name")
    files_changed: List[str] = Field(default_factory=list, description="List of modified file paths")
    deployment_env: Optional[str] = Field(default=None, description="Target environment (e.g. production, staging)")
    deployment_status: Optional[str] = Field(default="SUCCESS", description="Deployment state: SUCCESS, FAILED, ROLLED_BACK")
    relation_to_incident: Optional[str] = Field(
        default="SUSPECT",
        description="Temporal correlation: PRE_INCIDENT, COINCIDENT, POST_INCIDENT, UNRELATED",
    )
    evidence_reference: str = Field(..., description="Git commit URL or API reference")


class ChangeAnalystResult(BaseModel):
    """Complete structured output from Change Analyst Agent."""
    status: str = Field(default="COMPLETED", description="COMPLETED, FAILED, or PARTIAL")
    relevant_changes: List[ChangeItem] = Field(default_factory=list)
    change_count: int = 0
    deployments_detected: int = 0
    correlation_notes: Optional[str] = None
    error_message: Optional[str] = None


class HistoricalIncidentMatch(BaseModel):
    """Historical incident retrieved via semantic similarity search."""
    incident_id: Optional[int] = None
    source_incident_key: str
    title: str
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity score (0.0 - 1.0)")
    content: str
    resolution: str
    service_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
