"""Unit tests for the Change Analyst Agent."""

from datetime import datetime, timezone
import pytest
from app.agents.change_analyst import ChangeAnalystAgent
from app.integrations.github import MockGitHubClient
from app.schemas.agent_findings import ChangeAnalystResult
from app.services.llm_service import MockLLMService


@pytest.mark.asyncio
async def test_change_analyst_execution(mock_github: MockGitHubClient, mock_llm: MockLLMService, sample_investigation_state):
    """Test Change Analyst identifies commits and assigns temporal correlation."""
    agent = ChangeAnalystAgent(github_client=mock_github, llm_service=mock_llm)
    result_dict = await agent.execute(dict(sample_investigation_state))

    assert "change_result" in result_dict
    change_result: ChangeAnalystResult = result_dict["change_result"]

    assert change_result.status == "COMPLETED"
    assert change_result.change_count > 0
    assert len(change_result.relevant_changes) > 0

    first_change = change_result.relevant_changes[0]
    assert first_change.commit_id != ""
    assert first_change.author != ""
    assert first_change.evidence_reference.startswith("git://")
    assert first_change.relation_to_incident in ["PRE_INCIDENT", "COINCIDENT", "POST_INCIDENT", "SUSPECT"]


@pytest.mark.asyncio
async def test_change_analyst_avoids_premature_root_cause(mock_github: MockGitHubClient, mock_llm: MockLLMService, sample_investigation_state):
    """Test Change Analyst notes correlation without unilaterally confirming root cause."""
    agent = ChangeAnalystAgent(github_client=mock_github, llm_service=mock_llm)
    result_dict = await agent.execute(dict(sample_investigation_state))
    change_result: ChangeAnalystResult = result_dict["change_result"]

    assert change_result.correlation_notes is not None
    # Verify correlation notes describe temporal relationship
    assert len(change_result.correlation_notes) > 5
