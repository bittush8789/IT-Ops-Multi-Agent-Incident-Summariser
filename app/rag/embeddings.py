"""Embedding service abstraction with Google Gemini and deterministic offline mock implementations."""

import abc
import hashlib
import math
import logging
from typing import List, Optional
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class BaseEmbeddingService(abc.ABC):
    """Abstract base class for vector embedding generation."""

    @abc.abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """Generate a dense vector embedding for the input text."""
        pass

    @abc.abstractmethod
    def get_dimension(self) -> int:
        """Return the vector dimensionality."""
        pass


class GeminiEmbeddingService(BaseEmbeddingService):
    """Google Gemini embedding provider using models/text-embedding-004."""

    def __init__(self, api_key: str, model_name: str = "models/text-embedding-004", dimension: int = 768) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.dimension = dimension
        self._configured = False

    def _ensure_configured(self) -> None:
        if not self._configured:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._configured = True

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding using Gemini API."""
        try:
            self._ensure_configured()
            import google.generativeai as genai
            result = genai.embed_content(
                model=self.model_name,
                content=text,
                task_type="retrieval_document",
            )
            embedding = result.get("embedding", [])
            if not embedding:
                raise ValueError("Empty embedding returned by Gemini API")
            # Truncate or pad if dimension differs
            if len(embedding) > self.dimension:
                return embedding[: self.dimension]
            return embedding
        except Exception as exc:
            logger.error("Failed to generate Gemini embedding: %s", str(exc), exc_info=True)
            raise RuntimeError(f"Gemini embedding error: {exc}") from exc

    def get_dimension(self) -> int:
        return self.dimension


class MockEmbeddingService(BaseEmbeddingService):
    """
    Deterministic pseudo-random embedding generator for offline testing and local development.
    Uses SHA-256 hash of text to generate reproducible, normalized 768-dim float vectors.
    """

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension

    async def get_embedding(self, text: str) -> List[float]:
        """Generate a deterministic unit-length vector based on text content hash."""
        # Seed pseudo-random values using text hash
        raw_hash = hashlib.sha256(text.encode("utf-8")).digest()
        vector: List[float] = []
        for i in range(self.dimension):
            # Deterministic pseudo-random generation
            byte_val = raw_hash[i % len(raw_hash)]
            val = ((byte_val + i * 37) % 256) / 128.0 - 1.0
            vector.append(val)

        # Normalize to unit length (L2 norm)
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector

    def get_dimension(self) -> int:
        return self.dimension


def get_embedding_service(settings: Optional[Settings] = None) -> BaseEmbeddingService:
    """Factory to retrieve appropriate embedding service based on environment and API key availability."""
    cfg = settings or get_settings()
    if cfg.GEMINI_API_KEY and cfg.GEMINI_API_KEY.strip() and not cfg.GEMINI_API_KEY.startswith("your_"):
        return GeminiEmbeddingService(
            api_key=cfg.GEMINI_API_KEY,
            model_name=cfg.GEMINI_EMBEDDING_MODEL,
            dimension=cfg.EMBEDDING_DIMENSION,
        )
    return MockEmbeddingService(dimension=cfg.EMBEDDING_DIMENSION)
