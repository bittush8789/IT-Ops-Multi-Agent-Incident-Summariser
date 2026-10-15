"""End-to-end tests for the multi-agent LangGraph workflow."""

import pytest
from app.agents.change_analyst import ChangeAnalystAgent
from app.agents.log_analyst import LogAnalystAgent
from app.agents.report_writer import ReportWriterAgent
from app.agents.supervisor import SupervisorAgent
from app.graph.workflow import build_investigation_graph
from app.integrations.github import MockGitHubClient
from app.integrations.log_sources import FileLogSource
from app.services.llm_service import MockLLMService


@pytest.mark.asyncio
async def test_full_investigation_graph_execution(
    mock_llm: MockLLMService,
    mock_log_source: FileLogSource,
    mock_github: MockGitHubClient,
    sample_investigation_state,
):
    """Test full LangGraph investigation workflow runs from start to finish."""
    sup_agent = SupervisorAgent(llm_service=mock_llm)
    log_agent = LogAnalystAgent(log_source=mock_log_source, llm_service=mock_llm)
    change_agent = ChangeAnalystAgent(github_client=mock_github, llm_service=mock_llm)
    report_agent = ReportWriterAgent(llm_service=mock_llm)

    graph = build_investigation_graph(
        supervisor_agent=sup_agent,
        log_agent=log_agent,
        change_agent=change_agent,
        report_agent=report_agent,
    )

    final_state = await graph.ainvoke(sample_investigation_state)

    assert final_state["workflow_status"] in ("COMPLETED", "PARTIAL")
    assert final_state["step_count"] > 0
    assert "LogAnalyst" in final_state["completed_agents"]
    assert "ChangeAnalyst" in final_state["completed_agents"]
    assert "ReportWriter" in final_state["completed_agents"]
    assert final_state["final_report"] is not None
    assert final_state["investigation_plan"] is not None


@pytest.mark.asyncio
async def test_graph_validation_node_catches_invalid_scope():
    """Verify validate_scope node halts workflow when required fields are missing."""
    graph = build_investigation_graph()
    invalid_state = {
        "incident_id": None,
        "title": "",
        "service_name": "",
    }

    final_state = await graph.ainvoke(invalid_state)
    assert final_state["workflow_status"] == "FAILED"
    assert "scope_validation" in final_state["agent_errors"]
