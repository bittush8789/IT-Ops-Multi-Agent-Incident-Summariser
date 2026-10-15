"""Pytest configuration, shared fixtures, and mock test providers."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from app.config import Settings
from app.graph.state import InvestigationState
from app.integrations.github import MockGitHubClient
from app.integrations.log_sources import FileLogSource
from app.main import create_app
from app.rag.embeddings import MockEmbeddingService
from app.services.llm_service import MockLLMService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def test_settings() -> Settings:
    """Provide isolated settings for automated testing."""
    return Settings(
        APP_ENV="test",
        DEBUG=True,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        GEMINI_API_KEY=None,  # Force mock LLM
        GITHUB_USE_MOCK=True,
        GITHUB_FIXTURE_PATH=str(FIXTURES_DIR / "github_changes.json"),
        LOG_FIXTURE_PATH=str(FIXTURES_DIR / "incident_logs.json"),
        MAX_WORKFLOW_STEPS=10,
        AGENT_TIMEOUT_SECONDS=5,
        LANGFUSE_ENABLED=False,
        OTEL_ENABLED=False,
    )


@pytest.fixture
def mock_llm() -> MockLLMService:
    """Provide deterministic mock LLM service."""
    return MockLLMService()


@pytest.fixture
def mock_embedding() -> MockEmbeddingService:
    """Provide deterministic 768-dim mock embedding service."""
    return MockEmbeddingService(dimension=768)


@pytest.fixture
def mock_github() -> MockGitHubClient:
    """Provide mock GitHub client backed by fixture file."""
    return MockGitHubClient(FIXTURES_DIR / "github_changes.json")


@pytest.fixture
def mock_log_source() -> FileLogSource:
    """Provide mock log source backed by fixture file."""
    return FileLogSource(FIXTURES_DIR / "incident_logs.json")


@pytest.fixture
def sample_investigation_state() -> InvestigationState:
    """Provide realistic initial state for testing LangGraph workflow nodes."""
    now = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    return {
        "incident_id": 1,
        "incident_key": "INC-2026-1001",
        "title": "Payment Gateway Pool Timeout",
        "description": "Cascading HTTP 504 errors on checkout endpoints due to connection starvation.",
        "service_name": "payment-gateway",
        "severity": "CRITICAL",
        "started_at": now,
        "resolved_at": None,
        "max_steps": 10,
        "step_count": 0,
        "completed_agents": [],
        "failed_agents": [],
        "agent_errors": {},
        "retry_counts": {},
        "historical_matches": [],
        "workflow_status": "IN_PROGRESS",
    }


@pytest.fixture
def mock_incident_service() -> AsyncMock:
    """Provide mocked IncidentService for isolated API route testing."""
    from app.services.incident_service import IncidentService
    return AsyncMock(spec=IncidentService)


@pytest_asyncio.fixture
async def async_client(mock_incident_service: AsyncMock) -> AsyncGenerator[AsyncClient, None]:
    """Provide asynchronous HTTP test client for FastAPI routes with dependency override."""
    from app.api.dependencies import get_incident_service
    app = create_app()
    app.dependency_overrides[get_incident_service] = lambda: mock_incident_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
