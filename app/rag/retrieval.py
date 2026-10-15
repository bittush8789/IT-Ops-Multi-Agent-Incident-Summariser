"""Semantic retrieval service for finding historical incidents using pgvector."""

import logging
from typing import List, Optional
from app.database.repositories import IncidentKnowledgeRepository
from app.rag.embeddings import BaseEmbeddingService, get_embedding_service
from app.schemas.agent_findings import HistoricalIncidentMatch

logger = logging.getLogger(__name__)


class IncidentKnowledgeRetriever:
    """
    RAG service for historical incident knowledge retrieval.
    Matches current incident symptoms with prior resolved incidents to provide precedent solutions.
    """

    def __init__(
        self,
        repository: IncidentKnowledgeRepository,
        embedding_service: Optional[BaseEmbeddingService] = None,
    ) -> None:
        self.repository = repository
        self.embedding_service = embedding_service or get_embedding_service()

    async def retrieve_historical_context(
        self,
        title: str,
        description: str,
        service_name: Optional[str] = None,
        limit: int = 3,
        min_similarity: float = 0.25,
    ) -> List[HistoricalIncidentMatch]:
        """
        Embed incident title/description and perform similarity search against knowledge repository.
        Gracefully handles empty historical knowledge stores.
        """
        query_text = f"Incident: {title}. Details: {description}"
        if service_name:
            query_text += f". Affected Service: {service_name}"

        try:
            query_embedding = await self.embedding_service.get_embedding(query_text)
            matches = await self.repository.search_similar(
                query_embedding=query_embedding,
                limit=limit,
                service_name=service_name,
                min_similarity=min_similarity,
            )
            logger.info("Retrieved %d historical incident matches for query", len(matches))
            return matches
        except Exception as exc:
            # RAG retrieval should fail gracefully so the core investigation can continue
            logger.warning("Historical RAG retrieval encountered error or empty database: %s", str(exc))
            return []
