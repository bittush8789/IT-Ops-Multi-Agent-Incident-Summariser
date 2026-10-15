"""Main FastAPI application entry point for the IT-Ops Multi-Agent Incident Summariser."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import AsyncGenerator
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as incidents_router
from app.config import get_settings
from app.observability.langfuse_tracker import get_langfuse_tracker
from app.observability.telemetry import setup_telemetry

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("itops.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager handling application startup and graceful shutdown."""
    settings = get_settings()
    logger.info("Starting up %s in %s mode...", settings.APP_NAME, settings.APP_ENV)

    # Setup OpenTelemetry instrumentation if enabled
    setup_telemetry(app)

    yield

    logger.info("Shutting down %s...", settings.APP_NAME)
    # Flush Langfuse buffer if enabled
    tracker = get_langfuse_tracker()
    tracker.flush()


def create_app() -> FastAPI:
    """Application factory for FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description=(
            "Multi-Agent LangGraph system for automated IT-Ops incident analysis, "
            "log anomaly identification, GitHub change correlation, pgvector RAG, "
            "and Post-Incident Review (PIR) drafting."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers
    app.include_router(incidents_router)

    # Health check endpoint
    @app.get("/health", tags=["Health"], status_code=status.HTTP_200_OK)
    async def health_check():
        """Basic application health and status endpoint."""
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": "0.1.0",
            "environment": settings.APP_ENV,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Mount Frontend Static Assets
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        @app.get("/", tags=["Frontend"])
        async def serve_index():
            """Serve frontend dashboard interface."""
            index_path = frontend_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "Frontend index.html not found"}

    return app


app = create_app()
