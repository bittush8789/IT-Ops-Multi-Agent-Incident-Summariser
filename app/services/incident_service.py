"""Incident service orchestrating database persistence, RAG retrieval, and LangGraph workflow execution."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Incident, IncidentReport
from app.database.repositories import (
    AgentRunRepository,
    IncidentEventRepository,
    IncidentKnowledgeRepository,
    IncidentReportRepository,
    IncidentRepository,
)
from app.graph.state import InvestigationState
from app.observability.langfuse_tracker import get_langfuse_tracker
from app.rag.retrieval import IncidentKnowledgeRetriever
from app.schemas.incident import (
    AgentRunResponse,
    IncidentCreate,
    IncidentEventCreate,
    IncidentResponse,
    IncidentSeverity,
    IncidentStatus,
    IncidentUpdate,
    InvestigationExecutionStatus,
    InvestigationRequest,
    InvestigationStatusResponse,
)
from app.schemas.report import IncidentReportCreate, IncidentReportResponse, ReportRegenerateRequest

logger = logging.getLogger(__name__)


class IncidentService:
    """Core domain service for incident lifecycle and multi-agent investigation execution."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incident_repo = IncidentRepository(session)
        self.event_repo = IncidentEventRepository(session)
        self.agent_run_repo = AgentRunRepository(session)
        self.report_repo = IncidentReportRepository(session)
        self.knowledge_repo = IncidentKnowledgeRepository(session)
        self.retriever = IncidentKnowledgeRetriever(self.knowledge_repo)

    async def create_incident(self, incident_in: IncidentCreate) -> IncidentResponse:
        """Create a new incident record."""
        incident = await self.incident_repo.create(incident_in)
        return IncidentResponse.model_validate(incident)

    async def get_incident(self, incident_id: int) -> Optional[IncidentResponse]:
        """Retrieve an incident by ID."""
        incident = await self.incident_repo.get_by_id(incident_id)
        if not incident:
            return None
        return IncidentResponse.model_validate(incident)

    async def list_incidents(
        self,
        skip: int = 0,
        limit: int = 20,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> Tuple[List[IncidentResponse], int]:
        """List incidents with pagination and total count."""
        items = await self.incident_repo.list_incidents(
            skip=skip, limit=limit, severity=severity, status=status, service_name=service_name
        )
        total = await self.incident_repo.count_incidents(
            severity=severity, status=status, service_name=service_name
        )
        return [IncidentResponse.model_validate(i) for i in items], total

    async def run_investigation(
        self,
        incident_id: int,
        req: Optional[InvestigationRequest] = None,
    ) -> InvestigationStatusResponse:
        """Execute the LangGraph multi-agent investigation workflow for the incident."""
        incident = await self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise ValueError(f"Incident with ID {incident_id} not found")

        # Update operational status
        await self.incident_repo.update_status(incident_id, IncidentStatus.INVESTIGATING.value)

        # Initialize Langfuse root trace
        tracker = get_langfuse_tracker()
        trace_id = tracker.create_trace(
            name=f"investigation:{incident.incident_key}",
            session_id=str(incident.id),
            metadata={"incident_key": incident.incident_key, "service": incident.service_name},
        )

        # Prepare initial workflow state
        max_steps = (req.max_steps if req and req.max_steps else 12)
        initial_state: InvestigationState = {
            "incident_id": incident.id,
            "incident_key": incident.incident_key,
            "title": incident.title,
            "description": incident.description,
            "service_name": incident.service_name,
            "severity": incident.severity,
            "started_at": incident.started_at,
            "resolved_at": incident.resolved_at,
            "log_source_path": req.log_source_path if req else None,
            "github_repo": req.github_repo if req else None,
            "trace_id": trace_id,
            "max_steps": max_steps,
            "step_count": 0,
            "completed_agents": [],
            "failed_agents": [],
            "agent_errors": {},
            "retry_counts": {},
            "historical_matches": [],
            "workflow_status": "IN_PROGRESS",
        }

        # Build and execute the LangGraph workflow
        from app.graph.workflow import build_investigation_graph
        graph = build_investigation_graph(retriever=self.retriever)
        final_state: Dict[str, Any] = await graph.ainvoke(initial_state)

        # Audit agent executions in database
        completed_agents = final_state.get("completed_agents", [])
        failed_agents = final_state.get("failed_agents", [])
        agent_errors = final_state.get("agent_errors", {})

        for agent_name in ["Supervisor", "LogAnalyst", "ChangeAnalyst", "ReportWriter"]:
            if agent_name in completed_agents:
                await self.agent_run_repo.create_run(
                    incident_id=incident.id,
                    agent_name=agent_name,
                    status="COMPLETED",
                    steps_used=1,
                    metadata={"trace_id": trace_id},
                )
            elif agent_name in failed_agents:
                await self.agent_run_repo.create_run(
                    incident_id=incident.id,
                    agent_name=agent_name,
                    status="FAILED",
                    steps_used=1,
                    metadata={"error": agent_errors.get(agent_name), "trace_id": trace_id},
                )

        # Persist report if produced
        report_data = final_state.get("final_report")
        if report_data:
            report_create = IncidentReportCreate(
                incident_id=incident.id,
                **report_data.model_dump(),
            )
            await self.report_repo.create_or_update_report(report_create)

            # Persist timeline events to incident_events
            await self.event_repo.delete_by_incident(incident.id)
            for item in report_data.timeline:
                await self.event_repo.create_event(
                    IncidentEventCreate(
                        incident_id=incident.id,
                        event_type=item.event_type,
                        source=item.source,
                        description=item.description,
                        event_timestamp=item.timestamp,
                        evidence_reference=item.evidence_reference,
                        metadata={"is_inferred": item.is_inferred},
                    )
                )

        # Determine finalized status
        workflow_status = final_state.get("workflow_status", "COMPLETED")
        exec_status = InvestigationExecutionStatus.COMPLETED
        if workflow_status == "PARTIAL":
            exec_status = InvestigationExecutionStatus.PARTIAL
        elif workflow_status == "BUDGET_EXHAUSTED":
            exec_status = InvestigationExecutionStatus.BUDGET_EXHAUSTED
        elif workflow_status == "FAILED":
            exec_status = InvestigationExecutionStatus.FAILED

        # Update incident status in DB
        if exec_status in (InvestigationExecutionStatus.COMPLETED, InvestigationExecutionStatus.PARTIAL):
            await self.incident_repo.update_status(incident.id, IncidentStatus.MITIGATED.value)

        runs = await self.agent_run_repo.list_by_incident(incident.id)
        runs_response = [AgentRunResponse.model_validate(r) for r in runs]

        return InvestigationStatusResponse(
            incident_id=incident.id,
            incident_key=incident.incident_key,
            status=exec_status,
            steps_used=final_state.get("step_count", 0),
            max_steps=max_steps,
            completed_agents=completed_agents,
            failed_agents=failed_agents,
            has_report=report_data is not None,
            summary_message=f"Investigation concluded with status {exec_status.value}. Completed agents: {', '.join(completed_agents) if completed_agents else 'None'}",
            agent_runs=runs_response,
        )

    async def get_investigation_status(self, incident_id: int) -> Optional[InvestigationStatusResponse]:
        """Retrieve current investigation state and agent run logs."""
        incident = await self.incident_repo.get_by_id(incident_id)
        if not incident:
            return None

        runs = await self.agent_run_repo.list_by_incident(incident.id)
        runs_response = [AgentRunResponse.model_validate(r) for r in runs]
        report = await self.report_repo.get_by_incident_id(incident_id)

        completed = [r.agent_name for r in runs if r.status == "COMPLETED"]
        failed = [r.agent_name for r in runs if r.status == "FAILED"]

        status = InvestigationExecutionStatus.PENDING
        if report:
            status = InvestigationExecutionStatus.PARTIAL if failed else InvestigationExecutionStatus.COMPLETED
        elif runs:
            status = InvestigationExecutionStatus.IN_PROGRESS

        return InvestigationStatusResponse(
            incident_id=incident.id,
            incident_key=incident.incident_key,
            status=status,
            steps_used=sum(r.steps_used for r in runs),
            max_steps=12,
            completed_agents=completed,
            failed_agents=failed,
            has_report=report is not None,
            summary_message="Current investigation progress retrieved.",
            agent_runs=runs_response,
        )

    async def get_timeline(self, incident_id: int) -> List[Dict[str, Any]]:
        """Retrieve verified chronological timeline for an incident."""
        events = await self.event_repo.list_by_incident(incident_id)
        return [
            {
                "id": e.id,
                "incident_id": e.incident_id,
                "event_type": e.event_type,
                "source": e.source,
                "description": e.description,
                "timestamp": e.event_timestamp.isoformat(),
                "evidence_reference": e.evidence_reference,
                "metadata": e.metadata_,
            }
            for e in events
        ]

    async def get_report(self, incident_id: int) -> Optional[IncidentReportResponse]:
        """Fetch the generated report for an incident."""
        report = await self.report_repo.get_by_incident_id(incident_id)
        if not report:
            return None
        return IncidentReportResponse.model_validate(report)

    async def regenerate_report(
        self, incident_id: int, req: Optional[ReportRegenerateRequest] = None
    ) -> IncidentReportResponse:
        """Trigger re-investigation and report regeneration."""
        investigation_req = InvestigationRequest(force_refresh=True)
        await self.run_investigation(incident_id, investigation_req)
        report = await self.report_repo.get_by_incident_id(incident_id)
        if not report:
            raise RuntimeError("Report regeneration failed to produce report record")
        return IncidentReportResponse.model_validate(report)
