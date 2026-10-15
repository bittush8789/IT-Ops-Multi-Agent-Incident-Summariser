"""Database repository layer unit tests."""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.database.models import Incident, IncidentKnowledge, IncidentReport
from app.database.repositories import (
    AgentRunRepository,
    IncidentEventRepository,
    IncidentKnowledgeRepository,
    IncidentReportRepository,
    IncidentRepository,
)
from app.schemas.incident import IncidentCreate, IncidentEventCreate, IncidentSeverity, IncidentStatus
from app.schemas.report import IncidentReportCreate, PostIncidentReview


@pytest.mark.asyncio
async def test_incident_repository_create():
    """Test creating an incident properly sets fields and generates incident key."""
    session = AsyncMock()
    session.add = MagicMock()
    repo = IncidentRepository(session)

    incident_in = IncidentCreate(
        title="Database deadlock in order service",
        description="Transactions aborted due to cyclic locks on orders table.",
        service_name="order-service",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
    )

    incident = await repo.create(incident_in)
    assert incident.title == incident_in.title
    assert incident.service_name == "order-service"
    assert incident.incident_key.startswith("INC-")
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_incident_event_repository_create():
    """Test recording an incident event marker."""
    session = AsyncMock()
    session.add = MagicMock()
    repo = IncidentEventRepository(session)

    event_in = IncidentEventCreate(
        incident_id=1,
        event_type="ERROR_SURGE",
        source="LogAnalyst",
        description="First timeout observed",
        event_timestamp=datetime.now(timezone.utc),
        evidence_reference="incident_logs.json:L22",
        metadata={"count": 15},
    )

    event = await repo.create_event(event_in)
    assert event.incident_id == 1
    assert event.event_type == "ERROR_SURGE"
    assert event.evidence_reference == "incident_logs.json:L22"
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_agent_run_audit_lifecycle():
    """Test logging agent execution start and completion."""
    session = AsyncMock()
    session.add = MagicMock()
    repo = AgentRunRepository(session)

    run = await repo.create_run(
        incident_id=1,
        agent_name="LogAnalyst",
        status="IN_PROGRESS",
        steps_used=1,
    )
    assert run.agent_name == "LogAnalyst"
    assert run.status == "IN_PROGRESS"

    # Mock fetch for completion
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = run
    session.execute.return_value = mock_result

    completed_run = await repo.complete_run(
        run_id=1,
        status="COMPLETED",
        steps_used=1,
        token_usage={"prompt_tokens": 120, "completion_tokens": 45},
    )
    assert completed_run.status == "COMPLETED"
    assert completed_run.token_usage["prompt_tokens"] == 120


@pytest.mark.asyncio
async def test_incident_knowledge_empty_graceful():
    """Test semantic search over empty knowledge repository returns empty list safely."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute.return_value = mock_result

    repo = IncidentKnowledgeRepository(session)
    dummy_embedding = [0.1] * 768

    matches = await repo.search_similar(dummy_embedding, limit=3)
    assert matches == []
