"""Unit tests for the Report Writer Agent."""

from datetime import datetime, timezone
import pytest
from app.agents.report_writer import ReportWriterAgent
from app.schemas.agent_findings import (
    ChangeAnalystResult,
    ChangeItem,
    LogAnalystResult,
    LogFindingItem,
)
from app.schemas.report import IncidentReportBase
from app.services.llm_service import MockLLMService


@pytest.mark.asyncio
async def test_report_writer_synthesis(mock_llm: MockLLMService, sample_investigation_state):
    """Test Report Writer consumes specialist findings to produce complete PIR artifact."""
    now = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    state = dict(sample_investigation_state)
    state["log_result"] = LogAnalystResult(
        status="COMPLETED",
        earliest_error_timestamp=now,
        findings=[
            LogFindingItem(
                timestamp=now,
                service="payment-gateway",
                error_type="TIMEOUT",
                message="Pool timeout",
                evidence_reference="incident_logs.json:L22",
                is_fact=True,
            )
        ],
    )
    state["change_result"] = ChangeAnalystResult(
        status="COMPLETED",
        relevant_changes=[
            ChangeItem(
                commit_id="8f92bd3",
                author="alex.dev@corp.internal",
                message="fix(pool): reduce timeout",
                timestamp=now,
                repository="enterprise-org/payment-gateway",
                evidence_reference="git://repo/commit/8f92bd3",
            )
        ],
    )

    agent = ReportWriterAgent(llm_service=mock_llm)
    res = await agent.execute(state)

    assert "final_report" in res
    report: IncidentReportBase = res["final_report"]

    assert report.executive_summary != ""
    assert report.impact_summary != ""
    assert len(report.timeline) > 0
    assert len(report.root_cause_hypotheses) > 0
    assert len(report.recommendations) > 0
    assert report.post_incident_review is not None


@pytest.mark.asyncio
async def test_report_writer_timeline_ordering(mock_llm: MockLLMService, sample_investigation_state):
    """Ensure report timeline entries are strictly sorted chronologically."""
    agent = ReportWriterAgent(llm_service=mock_llm)
    res = await agent.execute(dict(sample_investigation_state))
    report: IncidentReportBase = res["final_report"]

    timeline = report.timeline
    for i in range(len(timeline) - 1):
        assert timeline[i].timestamp <= timeline[i + 1].timestamp


@pytest.mark.asyncio
async def test_report_writer_evidence_references_intact(mock_llm: MockLLMService, sample_investigation_state):
    """Ensure every timeline entry carries a verifiable evidence reference."""
    agent = ReportWriterAgent(llm_service=mock_llm)
    res = await agent.execute(dict(sample_investigation_state))
    report: IncidentReportBase = res["final_report"]

    for item in report.timeline:
        assert item.evidence_reference != ""
        assert len(item.evidence_reference) > 3
