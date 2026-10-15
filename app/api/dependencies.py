"""FastAPI dependency injection providers."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import get_db
from app.services.incident_service import IncidentService


async def get_incident_service(
    session: AsyncSession = Depends(get_db),
) -> IncidentService:
    """Provide initialized IncidentService with active database session."""
    return IncidentService(session=session)
