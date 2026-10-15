"""API validation and integration tests for FastAPI endpoints."""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock

from app.schemas.incident import (
    IncidentResponse,
    IncidentSeverity,
    IncidentStatus,
    InvestigationExecutionStatus,
    InvestigationStatusResponse,
)
from app.schemas.report import (
    ActionItem,
    IncidentReportResponse,
    PostIncidentReview,
    RootCauseHypothesis,
    TimelineEntry,
)


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Test health check endpoint returns 200 OK with expected payload."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_create_incident_validation_failure(async_client: AsyncClient):
    """Test incident creation fails with 422 if mandatory fields are missing."""
    invalid_payload = {
        "title": "Short",  # Too short, requires min 3 chars
    }
    response = await async_client.post("/api/v1/incidents", json=invalid_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_incident_success(async_client: AsyncClient, mock_incident_service: AsyncMock):
    """Test creating an incident returns 201 Created and validated response."""
    now = datetime.now(timezone.utc)
    mock_incident_service.create_incident.return_value = IncidentResponse(
        id=1,
        incident_key="INC-2026-1001",
        title="Payment Gateway Outage",
        description="Checkout timeout errors on payment microservice",
        service_name="payment-gateway",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
        created_at=now,
        updated_at=now,
    )
    payload = {
        "title": "Payment Gateway Outage",
        "description": "Checkout timeout errors on payment microservice",
        "service_name": "payment-gateway",
        "severity": "HIGH",
    }
    response = await async_client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["incident_key"] == "INC-2026-1001"
    assert data["service_name"] == "payment-gateway"


@pytest.mark.asyncio
async def test_list_incidents_success(async_client: AsyncClient, mock_incident_service: AsyncMock):
    """Test listing incidents returns paginated structure."""
    mock_incident_service.list_incidents.return_value = ([], 0)
    response = await async_client.get("/api/v1/incidents?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["page_size"] == 10


@pytest.mark.asyncio
async def test_get_incident_not_found(async_client: AsyncClient, mock_incident_service: AsyncMock):
    """Test 404 response when requesting non-existent incident."""
    mock_incident_service.get_incident.return_value = None
    response = await async_client.get("/api/v1/incidents/99999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_investigation_success(async_client: AsyncClient, mock_incident_service: AsyncMock):
    """Test triggering investigation returns structured status."""
    mock_incident_service.run_investigation.return_value = InvestigationStatusResponse(
        incident_id=1,
        incident_key="INC-2026-1001",
        status=InvestigationExecutionStatus.COMPLETED,
        steps_used=5,
        max_steps=12,
        completed_agents=["Supervisor", "LogAnalyst", "ChangeAnalyst", "ReportWriter"],
        failed_agents=[],
        has_report=True,
        summary_message="Completed successfully",
        agent_runs=[],
    )
    response = await async_client.post("/api/v1/incidents/1/investigate", json={"force_refresh": True})
    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == 1
    assert data["status"] == "COMPLETED"
    assert len(data["completed_agents"]) == 4


@pytest.mark.asyncio
async def test_get_timeline_endpoint(async_client: AsyncClient, mock_incident_service: AsyncMock):
    """Test retrieving chronological timeline events."""
    now = datetime.now(timezone.utc)
    mock_incident_service.get_incident.return_value = IncidentResponse(
        id=1,
        incident_key="INC-1",
        title="Sample Incident",
        description="Sample Description",
        service_name="payment-gateway",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
        created_at=now,
        updated_at=now,
    )
    mock_incident_service.get_timeline.return_value = [
        {
            "id": 1,
            "incident_id": 1,
            "event_type": "DEPLOYMENT",
            "source": "ChangeAnalyst",
            "description": "Deploy commit 8f92bd3",
            "timestamp": now.isoformat(),
            "evidence_reference": "git://repo/commit/8f92bd3",
            "metadata": {},
        }
    ]
    response = await async_client.get("/api/v1/incidents/1/timeline")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "DEPLOYMENT"


@pytest.mark.asyncio
async def test_get_report_endpoint(async_client: AsyncClient, mock_incident_service: AsyncMock):
    """Test retrieving synthesized post-incident report."""
    now = datetime.now(timezone.utc)
    entry = TimelineEntry(
        timestamp=now,
        event_type="ERROR_SURGE",
        source="LogAnalyst",
        description="Pool timeout",
        evidence_reference="incident_logs.json:L22",
    )
    rc = RootCauseHypothesis(
        hypothesis="Connection pool starvation",
        likelihood="HIGH",
        supporting_evidence=["incident_logs.json:L22"],
        contradicting_evidence=[],
        unknowns=[],
    )
    action = ActionItem(
        title="Revert timeout",
        description="Revert config parameter to 60s",
        priority="P0",
        owner_team="SRE",
    )
    pir = PostIncidentReview(
        summary="Service degradation summary",
        impact="142 checkout timeouts",
        contributing_factors=["Config deployment"],
        lessons_learned=["Test timeouts in staging"],
        timeline=[entry],
        follow_up_actions=[action],
    )
    mock_incident_service.get_report.return_value = IncidentReportResponse(
        id=1,
        incident_id=1,
        executive_summary="Executive summary text",
        impact_summary="Impact summary text",
        timeline=[entry],
        root_cause_hypotheses=[rc],
        recommendations=[action],
        post_incident_review=pir,
        confidence_notes="High confidence based on exact evidence match",
        created_at=now,
        updated_at=now,
    )
    response = await async_client.get("/api/v1/incidents/1/report")
    assert response.status_code == 200
    data = response.json()
    assert data["executive_summary"] == "Executive summary text"
    assert len(data["timeline"]) == 1
