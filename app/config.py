"""Application configuration module using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the IT-Ops Multi-Agent Incident Summariser."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Settings
    APP_NAME: str = "IT-Ops Multi-Agent Incident Summariser"
    APP_ENV: str = Field(default="development", description="Environment: development, staging, production")
    APP_HOST: str = Field(default="0.0.0.0", description="Host to bind application server")
    APP_PORT: int = Field(default=8000, description="Port to bind application server")
    DEBUG: bool = Field(default=False, description="Debug mode")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Database Settings
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/itops_incident_db",
        description="SQLAlchemy compatible database connection URL with psycopg driver",
    )
    DB_ECHO: bool = Field(default=False, description="Log SQL statements")
    DB_POOL_SIZE: int = Field(default=10, description="Connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=20, description="Maximum pool overflow")

    # Google Gemini Settings
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API Key")
    GEMINI_MODEL: str = Field(default="gemini-3.8-flash", description="Gemini chat model identifier (e.g. gemini-3.8-flash)")
    GEMINI_EMBEDDING_MODEL: str = Field(default="models/text-embedding-004", description="Gemini embedding model identifier")
    EMBEDDING_DIMENSION: int = Field(default=768, description="Dimension of vector embeddings")

    # GitHub Integration
    GITHUB_REPO: str = Field(default="enterprise-org/payment-gateway", description="Default GitHub repository target")
    GITHUB_TOKEN: Optional[str] = Field(default=None, description="Optional GitHub Personal Access Token")
    GITHUB_USE_MOCK: bool = Field(default=True, description="Whether to use mock GitHub client fixture")
    GITHUB_FIXTURE_PATH: str = Field(
        default="tests/fixtures/github_changes.json",
        description="Path to local fixture file for GitHub changes",
    )

    # Log Source Integration
    LOG_SOURCE_TYPE: str = Field(default="file", description="Log source type: 'file' or 'mock'")
    LOG_FIXTURE_PATH: str = Field(
        default="tests/fixtures/incident_logs.json",
        description="Path to local fixture file for incident logs",
    )

    # Multi-Agent Workflow Budget & Limits
    MAX_WORKFLOW_STEPS: int = Field(default=12, description="Maximum execution step budget for LangGraph workflow")
    AGENT_TIMEOUT_SECONDS: int = Field(default=30, description="Timeout in seconds per agent invocation")
    MAX_RETRIES: int = Field(default=2, description="Bounded retry attempts for transient agent errors")

    # Observability - Langfuse
    LANGFUSE_ENABLED: bool = Field(default=False, description="Enable Langfuse observability")
    LANGFUSE_PUBLIC_KEY: Optional[str] = Field(default=None, description="Langfuse public API key")
    LANGFUSE_SECRET_KEY: Optional[str] = Field(default=None, description="Langfuse secret API key")
    LANGFUSE_HOST: str = Field(default="https://cloud.langfuse.com", description="Langfuse server URL")

    # Observability - OpenTelemetry
    OTEL_ENABLED: bool = Field(default=False, description="Enable OpenTelemetry tracing")
    OTEL_SERVICE_NAME: str = Field(default="itops-incident-summariser", description="OTel service name")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(default="http://localhost:4317", description="OTel OTLP exporter endpoint")

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    FRONTEND_DIR: Path = Path(__file__).resolve().parent.parent / "frontend"


@lru_cache()
def get_settings() -> Settings:
    """Retrieve cached application settings instance."""
    return Settings()
