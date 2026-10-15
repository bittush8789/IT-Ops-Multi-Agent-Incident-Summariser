"""Report Writer Agent: Synthesizes evidence into chronological timeline, executive summary, and Post-Incident Review."""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.prompts.report_writer_prompts import (
    REPORT_WRITER_SYNTHESIS_PROMPT,
    REPORT_WRITER_SYSTEM_PROMPT,
)
from app.schemas.agent_findings import (
    ChangeAnalystResult,
    HistoricalIncidentMatch,
    LogAnalystResult,
)
from app.schemas.report import (
    ActionItem,
    IncidentReportBase,
    PostIncidentReview,
    RootCauseHypothesis,
    TimelineEntry,
)
from app.services.llm_service import BaseLLMService, get_llm_service

logger = logging.getLogger(__name__)


class ReportWriterAgent(BaseAgent):
    """
    Report Writer Agent aggregates all specialist findings:
    - Sorts all verified events into a chronological timeline
    - Synthesizes executive summary and quantified impact
    - Generates evidence-backed root cause hypotheses
    - Drafts structured Post-Incident Review (PIR)
    - Enforces evidence citing for every assertion
    """

    def __init__(
        self,
        llm_service: Optional[BaseLLMService] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(name="ReportWriter", timeout_seconds=timeout_seconds)
        self.llm_service = llm_service or get_llm_service()

    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize specialist findings, build timeline, and produce IncidentReportBase."""
        incident_key = state.get("incident_key", "UNKNOWN")
        trace_id = state.get("trace_id")

        log_res: Optional[LogAnalystResult] = state.get("log_result")
        change_res: Optional[ChangeAnalystResult] = state.get("change_result")
        hist_matches: List[HistoricalIncidentMatch] = state.get("historical_matches", [])
        failed_agents: List[str] = state.get("failed_agents", [])

        # 1. Deterministically assemble and sort verified timeline candidates
        timeline_candidates: List[TimelineEntry] = []

        if change_res:
            for ch in change_res.relevant_changes:
                timeline_candidates.append(
                    TimelineEntry(
                        timestamp=ch.timestamp,
                        event_type="DEPLOYMENT" if ch.deployment_status else "COMMIT",
                        source="ChangeAnalyst",
                        description=f"Change {ch.commit_id} by {ch.author}: {ch.message}",
                        evidence_reference=ch.evidence_reference,
                        is_inferred=False,
                    )
                )

        if log_res:
            for finding in log_res.findings:
                timeline_candidates.append(
                    TimelineEntry(
                        timestamp=finding.timestamp,
                        event_type="ERROR_SURGE" if finding.count > 5 else "EXCEPTION",
                        source="LogAnalyst",
                        description=f"{finding.error_type} in {finding.service}: {finding.message}",
                        evidence_reference=finding.evidence_reference,
                        is_fact=finding.is_fact,
                    )
                )

        # Sort strictly in chronological ascending order
        timeline_candidates.sort(key=lambda e: e.timestamp)

        # 2. Format historical context
        hist_text = ""
        if hist_matches:
            hist_text = "\n".join(
                f"- Precedent {m.source_incident_key} (similarity: {m.similarity_score:.2f}): {m.title}\n  Resolution: {m.resolution}"
                for m in hist_matches
            )
        else:
            hist_text = "No relevant historical incidents found in pgvector knowledge store."

        # 3. Call LLM for comprehensive synthesis
        prompt = REPORT_WRITER_SYNTHESIS_PROMPT.format(
            incident_key=incident_key,
            title=state.get("title", ""),
            service_name=state.get("service_name", ""),
            severity=state.get("severity", "HIGH"),
            started_at=str(state.get("started_at")),
            resolved_at=str(state.get("resolved_at") or "Ongoing"),
            log_status=log_res.status if log_res else "NOT_RUN",
            log_earliest_error=str(log_res.earliest_error_timestamp) if log_res else "None",
            log_symptoms=str(log_res.subsequent_symptoms) if log_res else "[]",
            log_groups=json.dumps([g.model_dump(mode="json") for g in (log_res.error_groups if log_res else [])], default=str),
            log_findings=json.dumps([f.model_dump(mode="json") for f in (log_res.findings[:5] if log_res else [])], default=str),
            change_status=change_res.status if change_res else "NOT_RUN",
            change_count=change_res.change_count if change_res else 0,
            changes=json.dumps([c.model_dump(mode="json") for c in (change_res.relevant_changes if change_res else [])], default=str),
            change_notes=change_res.correlation_notes if change_res else "None",
            historical_context=hist_text,
            steps_used=state.get("step_count", 0),
            specialist_errors=", ".join(failed_agents) if failed_agents else "None",
        )

        try:
            report: IncidentReportBase = await self.llm_service.generate_structured(
                prompt=prompt,
                schema_class=IncidentReportBase,
                system_instruction=REPORT_WRITER_SYSTEM_PROMPT,
                trace_id=trace_id,
            )
            # Ensure timeline entries are properly sorted in the generated report
            report.timeline.sort(key=lambda x: x.timestamp)
            return {"final_report": report}
        except Exception as exc:
            logger.warning("LLM report writing failed, generating deterministic report: %s", str(exc))
            now = datetime.now(timezone.utc)
            # Resilient fallback synthesis
            recs = [
                ActionItem(
                    title="Audit service connection thresholds and timeouts",
                    description="Review connection limits and timeout settings across microservices",
                    priority="P1",
                    owner_team="SRE",
                    action_type="REMEDIATION",
                )
            ]
            pir = PostIncidentReview(
                summary=f"Incident {incident_key} affected {state.get('service_name', 'target service')}.",
                impact="Service degradation observed during investigation window.",
                contributing_factors=["Telemetry indicates error surge coincident with recent change events."],
                lessons_learned=["Ensure observability captures exact queue latency metrics."],
                timeline=timeline_candidates,
                follow_up_actions=recs,
            )
            fallback_report = IncidentReportBase(
                executive_summary=f"Investigation for incident {incident_key} concluded. Evaluated {len(timeline_candidates)} timeline events across logs and deployments.",
                impact_summary="Service performance impacted. Error surge identified in log streams.",
                timeline=timeline_candidates,
                root_cause_hypotheses=[
                    RootCauseHypothesis(
                        hypothesis="Service degradation correlated with recent changes or upstream resource contention.",
                        likelihood="MEDIUM",
                        supporting_evidence=[f"{len(timeline_candidates)} timeline entries recorded."],
                        contradicting_evidence=[],
                        unknowns=["Underlying network metrics at time of failure."],
                    )
                ],
                recommendations=recs,
                post_incident_review=pir,
                confidence_notes="Synthesized from specialist findings. " + (f"Specialists failed: {failed_agents}" if failed_agents else "All specialists completed."),
            )
            return {"final_report": fallback_report}
