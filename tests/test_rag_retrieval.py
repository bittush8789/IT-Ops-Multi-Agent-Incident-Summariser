"""Unit tests for the RAG and pgvector historical incident retrieval module."""

import pytest
from unittest.mock import AsyncMock
from app.rag.embeddings import MockEmbeddingService
from app.rag.retrieval import IncidentKnowledgeRetriever
from app.schemas.agent_findings import HistoricalIncidentMatch


@pytest.mark.asyncio
async def test_mock_embedding_dimensions_and_norm():
    """Verify mock embedding generator returns unit-length 768-dimensional float vectors."""
    service = MockEmbeddingService(dimension=768)
    vector = await service.get_embedding("Database connection pool timeout in payment-gateway")

    assert len(vector) == 768
    # Check L2 unit normalization: sum of squares ≈ 1.0
    norm_sq = sum(x * x for x in vector)
    assert 0.99 <= norm_sq <= 1.01


@pytest.mark.asyncio
async def test_historical_retrieval_success(mock_embedding: MockEmbeddingService):
    """Test retrieval fetches and parses historical precedent matches."""
    repo = AsyncMock()
    repo.search_similar.return_value = [
        HistoricalIncidentMatch(
            source_incident_key="INC-2025-0819",
            title="Auth Service Pool Exhaustion",
            similarity_score=0.89,
            content="Auth service failed due to pool timeout.",
            resolution="Reverted pool timeout from 3s back to 45s.",
            service_name="auth-service",
            metadata={},
        )
    ]

    retriever = IncidentKnowledgeRetriever(repository=repo, embedding_service=mock_embedding)
    matches = await retriever.retrieve_historical_context(
        title="Payment pool timeout",
        description="Checkout requests timing out",
        service_name="payment-gateway",
    )

    assert len(matches) == 1
    assert matches[0].source_incident_key == "INC-2025-0819"
    assert 0.0 <= matches[0].similarity_score <= 1.0


@pytest.mark.asyncio
async def test_historical_retrieval_handles_repo_exception(mock_embedding: MockEmbeddingService):
    """Verify retriever fails gracefully and returns empty list when database errors."""
    repo = AsyncMock()
    repo.search_similar.side_effect = RuntimeError("Database unreachable")

    retriever = IncidentKnowledgeRetriever(repository=repo, embedding_service=mock_embedding)
    matches = await retriever.retrieve_historical_context(
        title="Any incident",
        description="Any description",
    )
    assert matches == []
