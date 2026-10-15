"""FastAPI router defining endpoints for incident management, multi-agent investigation, and reporting."""

import math
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_incident_service
from app.schemas.incident import (
    IncidentCreate,
    IncidentResponse,
    InvestigationRequest,
    InvestigationStatusResponse,
    PaginatedIncidentsResponse,
)
from app.schemas.report import (
    IncidentReportResponse,
    ReportRegenerateRequest,
)
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents & Investigations"])


@router.get(
    "",
    response_model=PaginatedIncidentsResponse,
    summary="List incidents with pagination and filters",
)
async def list_incidents(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    severity: Optional[str] = Query(default=None, description="Filter by severity: LOW, MEDIUM, HIGH, CRITICAL"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status: OPEN, INVESTIGATING, MITIGATED, RESOLVED, CLOSED"),
    service_name: Optional[str] = Query(default=None, description="Filter by affected service name"),
    service: IncidentService = Depends(get_incident_service),
) -> PaginatedIncidentsResponse:
    """Retrieve paginated incidents with optional filters."""
    skip = (page - 1) * page_size
    items, total = await service.list_incidents(
        skip=skip,
        limit=page_size,
        severity=severity,
        status=status_filter,
        service_name=service_name,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return PaginatedIncidentsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new incident",
)
async def create_incident(
    incident_in: IncidentCreate,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Create and persist a new incident record."""
    return await service.create_incident(incident_in)


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Retrieve incident details",
)
async def get_incident(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Retrieve full incident details by primary ID."""
    incident = await service.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id} not found",
        )
    return incident


@router.post(
    "/{incident_id}/investigate",
    response_model=InvestigationStatusResponse,
    summary="Start an automated multi-agent investigation",
)
async def start_investigation(
    incident_id: int,
    req: Optional[InvestigationRequest] = None,
    service: IncidentService = Depends(get_incident_service),
) -> InvestigationStatusResponse:
    """
    Trigger LangGraph multi-agent investigation:
    Runs Supervisor, Log Analyst, Change Analyst, pgvector RAG, and Report Writer.
    """
    try:
        return await service.run_investigation(incident_id, req)
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Investigation failed: {str(exc)}",
        )


@router.get(
    "/{incident_id}/investigation",
    response_model=InvestigationStatusResponse,
    summary="Retrieve investigation status and agent run audit",
)
async def get_investigation_status(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
) -> InvestigationStatusResponse:
    """Retrieve execution progress, agent run logs, and completion status."""
    res = await service.get_investigation_status(incident_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id} not found",
        )
    return res


@router.get(
    "/{incident_id}/timeline",
    response_model=List[Dict[str, Any]],
    summary="Retrieve the event timeline",
)
async def get_incident_timeline(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
) -> List[Dict[str, Any]]:
    """Retrieve verified chronological timeline events with evidence references."""
    incident = await service.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id} not found",
        )
    return await service.get_timeline(incident_id)


@router.get(
    "/{incident_id}/report",
    response_model=IncidentReportResponse,
    summary="Retrieve the generated post-incident report",
)
async def get_incident_report(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentReportResponse:
    """Fetch executive summary, PIR, root cause hypotheses, and recommendations."""
    report = await service.get_report(incident_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report not yet generated for incident {incident_id}. Please run investigation first.",
        )
    return report


@router.post(
    "/{incident_id}/report/regenerate",
    response_model=IncidentReportResponse,
    summary="Request report regeneration",
)
async def regenerate_report(
    incident_id: int,
    req: Optional[ReportRegenerateRequest] = None,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentReportResponse:
    """Re-run evidence synthesis and regenerate the incident report."""
    incident = await service.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id} not found",
        )
    try:
        return await service.regenerate_report(incident_id, req)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report regeneration failed: {str(exc)}",
        )
