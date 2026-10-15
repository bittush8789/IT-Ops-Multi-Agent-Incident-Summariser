"""Database repository operations for incidents, events, agent runs, reports, and vector knowledge."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    AgentRun,
    Incident,
    IncidentEvent,
    IncidentKnowledge,
    IncidentReport,
)
from app.schemas.incident import (
    IncidentCreate,
    IncidentEventCreate,
    IncidentSeverity,
    IncidentStatus,
    IncidentUpdate,
)
from app.schemas.agent_findings import HistoricalIncidentMatch
from app.schemas.report import IncidentReportCreate


class IncidentRepository:
    """Data access layer for incidents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, incident_in: IncidentCreate) -> Incident:
        """Create a new incident with auto-generated key if not specified."""
        key = incident_in.incident_key
        if not key:
            # Deterministic auto-generated key with timestamp
            now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            key = f"INC-{now_str}"

        incident = Incident(
            incident_key=key,
            title=incident_in.title,
            description=incident_in.description,
            service_name=incident_in.service_name,
            severity=incident_in.severity.value if isinstance(incident_in.severity, IncidentSeverity) else str(incident_in.severity),
            status=incident_in.status.value if isinstance(incident_in.status, IncidentStatus) else str(incident_in.status),
            started_at=incident_in.started_at,
            resolved_at=incident_in.resolved_at,
        )
        self.session.add(incident)
        await self.session.flush()
        await self.session.refresh(incident)
        return incident

    async def get_by_id(self, incident_id: int, include_relations: bool = False) -> Optional[Incident]:
        """Fetch an incident by primary key."""
        query = select(Incident).where(Incident.id == incident_id)
        if include_relations:
            query = query.options(
                selectinload(Incident.events),
                selectinload(Incident.agent_runs),
                selectinload(Incident.report),
            )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_key(self, incident_key: str) -> Optional[Incident]:
        """Fetch an incident by human-readable key."""
        query = select(Incident).where(Incident.incident_key == incident_key)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_incidents(
        self,
        skip: int = 0,
        limit: int = 20,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> Sequence[Incident]:
        """List incidents with filtering and pagination."""
        query = select(Incident).order_by(desc(Incident.created_at)).offset(skip).limit(limit)
        if severity:
            query = query.where(Incident.severity == severity)
        if status:
            query = query.where(Incident.status == status)
        if service_name:
            query = query.where(Incident.service_name == service_name)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def count_incidents(
        self,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> int:
        """Count total matching incidents."""
        query = select(func.count(Incident.id))
        if severity:
            query = query.where(Incident.severity == severity)
        if status:
            query = query.where(Incident.status == status)
        if service_name:
            query = query.where(Incident.service_name == service_name)
        result = await self.session.execute(query)
        return result.scalar_one() or 0

    async def update(self, incident_id: int, update_data: IncidentUpdate) -> Optional[Incident]:
        """Update incident attributes."""
        incident = await self.get_by_id(incident_id)
        if not incident:
            return None
        dump = update_data.model_dump(exclude_unset=True)
        for key, value in dump.items():
            if value is not None:
                if isinstance(value, (IncidentSeverity, IncidentStatus)):
                    value = value.value
                setattr(incident, key, value)
        await self.session.flush()
        await self.session.refresh(incident)
        return incident

    async def update_status(self, incident_id: int, new_status: str) -> Optional[Incident]:
        """Update operational status."""
        incident = await self.get_by_id(incident_id)
        if incident:
            incident.status = new_status
            await self.session.flush()
            await self.session.refresh(incident)
        return incident


class IncidentEventRepository:
    """Data access layer for chronological incident events and timeline markers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(self, event_in: IncidentEventCreate) -> IncidentEvent:
        """Record an event associated with an incident."""
        event = IncidentEvent(
            incident_id=event_in.incident_id,
            event_type=event_in.event_type,
            source=event_in.source,
            description=event_in.description,
            event_timestamp=event_in.event_timestamp,
            evidence_reference=event_in.evidence_reference,
            metadata_=event_in.metadata,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def list_by_incident(self, incident_id: int) -> Sequence[IncidentEvent]:
        """Fetch all events for an incident sorted chronologically."""
        query = (
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.event_timestamp.asc())
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def delete_by_incident(self, incident_id: int) -> int:
        """Delete existing events for an incident (used during investigation replay/refresh)."""
        from sqlalchemy import delete
        stmt = delete(IncidentEvent).where(IncidentEvent.incident_id == incident_id)
        result = await self.session.execute(stmt)
        return result.rowcount or 0


class AgentRunRepository:
    """Audit repository for tracking execution runs of each AI agent."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_run(
        self,
        incident_id: int,
        agent_name: str,
        status: str = "IN_PROGRESS",
        steps_used: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentRun:
        """Log the start of an agent run."""
        run = AgentRun(
            incident_id=incident_id,
            agent_name=agent_name,
            status=status,
            steps_used=steps_used,
            started_at=datetime.now(timezone.utc),
            metadata_=metadata or {},
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def complete_run(
        self,
        run_id: int,
        status: str,
        steps_used: int,
        error_message: Optional[str] = None,
        token_usage: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentRun]:
        """Update agent run completion state."""
        query = select(AgentRun).where(AgentRun.id == run_id)
        result = await self.session.execute(query)
        run = result.scalar_one_or_none()
        if not run:
            return None
        run.status = status
        run.steps_used = steps_used
        run.completed_at = datetime.now(timezone.utc)
        run.error_message = error_message
        if token_usage:
            run.token_usage = token_usage
        if metadata:
            current_meta = dict(run.metadata_ or {})
            current_meta.update(metadata)
            run.metadata_ = current_meta
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def list_by_incident(self, incident_id: int) -> Sequence[AgentRun]:
        """List all agent runs for an incident."""
        query = select(AgentRun).where(AgentRun.incident_id == incident_id).order_by(AgentRun.started_at.asc())
        result = await self.session.execute(query)
        return result.scalars().all()


class IncidentReportRepository:
    """Data access layer for final executive reports and PIRs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update_report(self, report_in: IncidentReportCreate) -> IncidentReport:
        """Persist or update an incident report."""
        query = select(IncidentReport).where(IncidentReport.incident_id == report_in.incident_id)
        result = await self.session.execute(query)
        report = result.scalar_one_or_none()

        timeline_data = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in report_in.timeline]
        root_causes_data = [rc.model_dump(mode="json") if hasattr(rc, "model_dump") else rc for rc in report_in.root_cause_hypotheses]
        recs_data = [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in report_in.recommendations]
        pir_data = report_in.post_incident_review.model_dump(mode="json") if hasattr(report_in.post_incident_review, "model_dump") else report_in.post_incident_review

        if report:
            report.executive_summary = report_in.executive_summary
            report.impact_summary = report_in.impact_summary
            report.timeline = timeline_data
            report.root_cause_hypotheses = root_causes_data
            report.recommendations = recs_data
            report.post_incident_review = pir_data
            report.confidence_notes = report_in.confidence_notes
            report.updated_at = datetime.now(timezone.utc)
        else:
            report = IncidentReport(
                incident_id=report_in.incident_id,
                executive_summary=report_in.executive_summary,
                impact_summary=report_in.impact_summary,
                timeline=timeline_data,
                root_cause_hypotheses=root_causes_data,
                recommendations=recs_data,
                post_incident_review=pir_data,
                confidence_notes=report_in.confidence_notes,
            )
            self.session.add(report)

        await self.session.flush()
        await self.session.refresh(report)
        return report

    async def get_by_incident_id(self, incident_id: int) -> Optional[IncidentReport]:
        """Fetch report by incident ID."""
        query = select(IncidentReport).where(IncidentReport.incident_id == incident_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


class IncidentKnowledgeRepository:
    """Data access layer for pgvector similarity search over historical incidents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_knowledge(
        self,
        content: str,
        resolution: str,
        embedding: List[float],
        source_incident_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IncidentKnowledge:
        """Store an incident knowledge entry with its vector embedding."""
        item = IncidentKnowledge(
            source_incident_id=source_incident_id,
            content=content,
            resolution=resolution,
            embedding=embedding,
            metadata_=metadata or {},
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def search_similar(
        self,
        query_embedding: List[float],
        limit: int = 3,
        service_name: Optional[str] = None,
        min_similarity: float = 0.3,
    ) -> List[HistoricalIncidentMatch]:
        """
        Perform cosine similarity search on historical incident knowledge.
        Gracefully returns an empty list if no knowledge is stored.
        """
        # In pgvector: cosine distance operator is `<=>`.
        # Cosine similarity = 1 - (embedding <=> query_embedding)
        cosine_distance = IncidentKnowledge.embedding.cosine_distance(query_embedding)
        cosine_similarity = 1 - cosine_distance

        query = select(
            IncidentKnowledge,
            cosine_similarity.label("similarity"),
        ).order_by(cosine_distance.asc()).limit(limit)

        result = await self.session.execute(query)
        rows = result.all()

        matches: List[HistoricalIncidentMatch] = []
        for row in rows:
            knowledge_entry: IncidentKnowledge = row[0]
            sim_score: float = float(row[1])

            # Apply similarity threshold
            if sim_score < min_similarity:
                continue

            # Optional service metadata filter if configured
            entry_service = knowledge_entry.metadata_.get("service_name")
            if service_name and entry_service and entry_service.lower() != service_name.lower():
                # Allow cross-service matches with slight score reduction if relevant, or keep strict
                pass

            matches.append(
                HistoricalIncidentMatch(
                    incident_id=knowledge_entry.source_incident_id,
                    source_incident_key=knowledge_entry.metadata_.get("incident_key", f"HIST-{knowledge_entry.id}"),
                    title=knowledge_entry.metadata_.get("title", "Historical Incident"),
                    similarity_score=round(max(0.0, min(1.0, sim_score)), 4),
                    content=knowledge_entry.content,
                    resolution=knowledge_entry.resolution,
                    service_name=entry_service,
                    metadata=knowledge_entry.metadata_,
                )
            )

        return matches
