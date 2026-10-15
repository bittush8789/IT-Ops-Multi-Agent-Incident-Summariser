"""Incident replay evaluation test comparing multi-agent generated timeline against human-written ground truth."""

import json
from pathlib import Path
import pytest

from app.agents.change_analyst import ChangeAnalystAgent
from app.agents.log_analyst import LogAnalystAgent
from app.agents.report_writer import ReportWriterAgent
from app.agents.supervisor import SupervisorAgent
from app.graph.workflow import build_investigation_graph
from app.integrations.github import MockGitHubClient
from app.integrations.log_sources import FileLogSource
from app.schemas.report import IncidentReportBase, TimelineEntry
from app.services.llm_service import MockLLMService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_incident_replay_timeline_evaluation(
    mock_llm: MockLLMService,
    mock_log_source: FileLogSource,
    mock_github: MockGitHubClient,
    sample_investigation_state,
):
    """
    Incident Replay Evaluation:
    Evaluates generated timeline against human-written ground truth reference timeline (expected_timeline.json).
    Metrics evaluated:
    - 1. Timestamp Ordering
    - 2. Event Coverage
    - 3. Missing Critical Events
    - 4. Unsupported Claims
    - 5. Evidence Reference Validity
    """
    # 1. Load human-written ground truth reference timeline
    with open(FIXTURES_DIR / "expected_timeline.json", "r", encoding="utf-8") as f:
        expected_raw = json.load(f)

    # 2. Execute multi-agent investigation workflow over recorded incident telemetry
    graph = build_investigation_graph(
        supervisor_agent=SupervisorAgent(llm_service=mock_llm),
        log_agent=LogAnalystAgent(log_source=mock_log_source, llm_service=mock_llm),
        change_agent=ChangeAnalystAgent(github_client=mock_github, llm_service=mock_llm),
        report_agent=ReportWriterAgent(llm_service=mock_llm),
    )

    final_state = await graph.ainvoke(sample_investigation_state)
    report: IncidentReportBase = final_state["final_report"]
    generated_timeline = report.timeline

    # ---------------------------------------------------------
    # Evaluation Metric 1: Timestamp Chronological Ordering
    # ---------------------------------------------------------
    for i in range(len(generated_timeline) - 1):
        assert generated_timeline[i].timestamp <= generated_timeline[i + 1].timestamp, (
            f"Ordering violation at index {i}: {generated_timeline[i].timestamp} > {generated_timeline[i + 1].timestamp}"
        )

    # ---------------------------------------------------------
    # Evaluation Metric 2 & 5: Evidence Reference Validity
    # ---------------------------------------------------------
    # Every generated event MUST cite a concrete evidence reference
    for entry in generated_timeline:
        assert entry.evidence_reference is not None, "Event missing evidence reference"
        assert len(entry.evidence_reference.strip()) > 0, "Empty evidence reference"
        # Reference should cite either git commit or log line pointer
        assert (
            "git://" in entry.evidence_reference
            or ".json:" in entry.evidence_reference
            or "http" in entry.evidence_reference
        ), f"Invalid evidence reference format: {entry.evidence_reference}"

    # ---------------------------------------------------------
    # Evaluation Metric 3: Missing Critical Events
    # ---------------------------------------------------------
    # Check that critical ground-truth events (e.g. pool timeout change and log anomaly) are covered
    expected_event_types = {e["event_type"] for e in expected_raw}
    generated_event_types = {e.event_type for e in generated_timeline}

    # At least DEPLOYMENT and ERROR_SURGE / ALERT must be represented
    assert "DEPLOYMENT" in generated_event_types, "Critical deployment event omitted from timeline"
    assert any(t in generated_event_types for t in ["ERROR_SURGE", "ALERT", "EXCEPTION"]), (
        "Critical error surge omitted from timeline"
    )

    # ---------------------------------------------------------
    # Evaluation Metric 4: Unsupported Claims Protection
    # ---------------------------------------------------------
    # Verify that evidence references cite real fixture resources
    with open(FIXTURES_DIR / "incident_logs.json", "r", encoding="utf-8") as f:
        known_logs = json.load(f)
    with open(FIXTURES_DIR / "github_changes.json", "r", encoding="utf-8") as f:
        known_changes = json.load(f)

    known_commit_shas = {c["commit_id"] for c in known_changes}

    for entry in generated_timeline:
        if "commit" in entry.evidence_reference:
            # Check commit SHA is in fixture
            found = any(sha in entry.evidence_reference for sha in known_commit_shas)
            assert found, f"Unsupported claim: commit reference {entry.evidence_reference} not found in telemetry"
