"""Unit tests for the Log Analyst Agent."""

from datetime import datetime, timezone
import pytest
from app.agents.log_analyst import LogAnalystAgent
from app.integrations.log_sources import FileLogSource
from app.schemas.agent_findings import LogAnalystResult
from app.services.llm_service import MockLLMService


@pytest.mark.asyncio
async def test_log_analyst_execution(mock_log_source: FileLogSource, mock_llm: MockLLMService, sample_investigation_state):
    """Test Log Analyst successfully parses logs and extracts structured error patterns."""
    agent = LogAnalystAgent(log_source=mock_log_source, llm_service=mock_llm)
    result_dict = await agent.execute(dict(sample_investigation_state))

    assert "log_result" in result_dict
    log_result: LogAnalystResult = result_dict["log_result"]

    assert log_result.status == "COMPLETED"
    assert log_result.raw_log_count > 0
    assert log_result.errors_detected > 0
    assert log_result.earliest_error_timestamp is not None
    assert len(log_result.error_groups) > 0


@pytest.mark.asyncio
async def test_log_analyst_distinguishes_facts_and_evidence(mock_log_source: FileLogSource, mock_llm: MockLLMService, sample_investigation_state):
    """Verify Log Analyst includes evidence references and verifies factual findings."""
    agent = LogAnalystAgent(log_source=mock_log_source, llm_service=mock_llm)
    result_dict = await agent.execute(dict(sample_investigation_state))
    log_result: LogAnalystResult = result_dict["log_result"]

    for finding in log_result.findings:
        assert finding.evidence_reference != ""
        assert ":" in finding.evidence_reference  # e.g. incident_logs.json:L45
        assert finding.is_fact is True


@pytest.mark.asyncio
async def test_log_analyst_empty_log_handling(mock_llm: MockLLMService, sample_investigation_state):
    """Verify Log Analyst handles missing or empty log files gracefully."""
    empty_source = FileLogSource("non_existent_file.json")
    agent = LogAnalystAgent(log_source=empty_source, llm_service=mock_llm)

    # State with service filter that yields no matches
    state = dict(sample_investigation_state)
    state["service_name"] = "completely-unknown-service"

    result_dict = await agent.execute(state)
    log_result: LogAnalystResult = result_dict["log_result"]
    assert log_result.status == "COMPLETED"
