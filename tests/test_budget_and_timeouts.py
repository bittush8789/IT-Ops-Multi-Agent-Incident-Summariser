"""Tests for workflow step budget, execution limits, agent timeouts, and failure resilience."""

import asyncio
from typing import Any, Dict
import pytest
from unittest.mock import AsyncMock

from app.agents.base import BaseAgent
from app.agents.supervisor import SupervisorAgent
from app.graph.workflow import build_investigation_graph
from app.services.llm_service import MockLLMService


class HangingAgent(BaseAgent):
    """Synthetic agent that sleeps indefinitely to test timeout enforcement."""

    def __init__(self, name: str, timeout_seconds: int = 1):
        super().__init__(name=name, timeout_seconds=timeout_seconds)

    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(10)  # Exceeds 1s timeout
        return {"status": "SUCCESS"}


class FailingAgent(BaseAgent):
    """Synthetic agent that raises unhandled exception."""

    def __init__(self, name: str):
        super().__init__(name=name, timeout_seconds=5)

    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectionResetError("Remote telemetry cluster disconnected")


@pytest.mark.asyncio
async def test_agent_timeout_enforcement():
    """Verify that an agent exceeding its configured timeout returns TIMEOUT status safely."""
    hanging_agent = HangingAgent(name="SlowAgent", timeout_seconds=1)
    res = await hanging_agent.execute({})

    assert res["status"] == "TIMEOUT"
    assert "timed out" in res["error_message"].lower()


@pytest.mark.asyncio
async def test_agent_exception_safety():
    """Verify that an agent raising an exception is caught and returns FAILED status."""
    failing_agent = FailingAgent(name="FaultyAgent")
    res = await failing_agent.execute({})

    assert res["status"] == "FAILED"
    assert "disconnected" in res["error_message"].lower()


@pytest.mark.asyncio
async def test_maximum_step_budget_exhaustion(mock_llm: MockLLMService, sample_investigation_state):
    """Test workflow terminates deterministically when max_steps budget is reached."""
    sup = SupervisorAgent(llm_service=mock_llm)

    # State with step_count already equal to max_steps
    state = dict(sample_investigation_state)
    state["step_count"] = 10
    state["max_steps"] = 10

    res = await sup.execute(state)
    assert res["workflow_status"] == "BUDGET_EXHAUSTED"
    assert res["next_step"] == "end"


@pytest.mark.asyncio
async def test_partial_completion_when_specialist_fails(
    mock_llm: MockLLMService,
    sample_investigation_state,
):
    """Verify workflow generates partial report when one specialist fails."""
    # Use failing change analyst mock
    failing_change = FailingAgent(name="ChangeAnalyst")

    graph = build_investigation_graph(
        supervisor_agent=SupervisorAgent(llm_service=mock_llm),
        change_agent=failing_change,  # type: ignore
    )

    final_state = await graph.ainvoke(sample_investigation_state)
    assert "ChangeAnalyst" in final_state["failed_agents"]
    assert final_state["workflow_status"] == "PARTIAL"
    assert final_state["final_report"] is not None
