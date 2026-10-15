"""Node implementations for the LangGraph incident investigation workflow."""

import logging
from typing import Any, Dict, List, Optional
from app.agents.change_analyst import ChangeAnalystAgent
from app.agents.log_analyst import LogAnalystAgent
from app.agents.report_writer import ReportWriterAgent
from app.agents.supervisor import SupervisorAgent
from app.graph.state import InvestigationState
from app.rag.retrieval import IncidentKnowledgeRetriever
from app.schemas.agent_findings import ChangeAnalystResult, LogAnalystResult

logger = logging.getLogger(__name__)


async def validate_scope_node(state: InvestigationState) -> Dict[str, Any]:
    """Node 1: Validate incident details and initialize execution tracking."""
    incident_id = state.get("incident_id")
    title = state.get("title")
    service_name = state.get("service_name")

    if not incident_id or not title or not service_name:
        return {
            "workflow_status": "FAILED",
            "agent_errors": {"scope_validation": "Missing mandatory incident parameters (id, title, or service_name)"},
            "next_step": "end",
        }

    return {
        "step_count": 0,
        "max_steps": state.get("max_steps", 12),
        "completed_agents": [],
        "failed_agents": [],
        "agent_errors": {},
        "retry_counts": {},
        "workflow_status": "IN_PROGRESS",
    }


async def supervisor_node(
    state: InvestigationState,
    supervisor_agent: Optional[SupervisorAgent] = None,
) -> Dict[str, Any]:
    """Node 2: Supervisor plans investigation, checks step budget, and routes next action."""
    agent = supervisor_agent or SupervisorAgent()
    result = await agent.execute(dict(state))

    step_count = result.get("step_count", state.get("step_count", 0))
    next_step = result.get("next_step", "dispatch_specialists")
    status = result.get("workflow_status", state.get("workflow_status", "IN_PROGRESS"))

    return {
        "step_count": step_count,
        "investigation_plan": result.get("investigation_plan"),
        "supervisor_notes": result.get("supervisor_notes"),
        "next_step": next_step,
        "workflow_status": status,
    }


async def log_analyst_node(
    state: InvestigationState,
    log_agent: Optional[LogAnalystAgent] = None,
) -> Dict[str, Any]:
    """Node 3: Execute Log Analyst to detect errors, spikes, and 5xx anomalies."""
    step_count = state.get("step_count", 0) + 1
    completed = list(state.get("completed_agents", []))
    failed = list(state.get("failed_agents", []))
    errors = dict(state.get("agent_errors", {}))

    # Avoid duplicate execution if already present
    if "LogAnalyst" in completed and state.get("log_result"):
        return {"step_count": step_count}

    agent = log_agent or LogAnalystAgent()
    res = await agent.execute(dict(state))

    log_result: Optional[LogAnalystResult] = res.get("log_result")
    if log_result and log_result.status != "FAILED":
        completed.append("LogAnalyst")
        return {
            "step_count": step_count,
            "log_result": log_result,
            "completed_agents": completed,
        }
    else:
        failed.append("LogAnalyst")
        err_msg = res.get("error_message", "LogAnalyst execution failed")
        errors["LogAnalyst"] = err_msg
        return {
            "step_count": step_count,
            "failed_agents": failed,
            "agent_errors": errors,
        }


async def change_analyst_node(
    state: InvestigationState,
    change_agent: Optional[ChangeAnalystAgent] = None,
) -> Dict[str, Any]:
    """Node 4: Execute Change Analyst to inspect commits, PRs, and deployments."""
    step_count = state.get("step_count", 0) + 1
    completed = list(state.get("completed_agents", []))
    failed = list(state.get("failed_agents", []))
    errors = dict(state.get("agent_errors", {}))

    # Avoid duplicate execution if already present
    if "ChangeAnalyst" in completed and state.get("change_result"):
        return {"step_count": step_count}

    agent = change_agent or ChangeAnalystAgent()
    res = await agent.execute(dict(state))

    change_result: Optional[ChangeAnalystResult] = res.get("change_result")
    if change_result and change_result.status != "FAILED":
        completed.append("ChangeAnalyst")
        return {
            "step_count": step_count,
            "change_result": change_result,
            "completed_agents": completed,
        }
    else:
        failed.append("ChangeAnalyst")
        err_msg = res.get("error_message", "ChangeAnalyst execution failed")
        errors["ChangeAnalyst"] = err_msg
        return {
            "step_count": step_count,
            "failed_agents": failed,
            "agent_errors": errors,
        }


async def rag_retrieval_node(
    state: InvestigationState,
    retriever: Optional[IncidentKnowledgeRetriever] = None,
) -> Dict[str, Any]:
    """Node 5: Retrieve similar historical incidents using pgvector embeddings."""
    if not retriever:
        # If no custom retriever injected, return empty matches gracefully
        return {"historical_matches": []}

    matches = await retriever.retrieve_historical_context(
        title=state.get("title", ""),
        description=state.get("description", ""),
        service_name=state.get("service_name"),
        limit=3,
    )
    return {"historical_matches": matches}


async def report_writer_node(
    state: InvestigationState,
    report_agent: Optional[ReportWriterAgent] = None,
) -> Dict[str, Any]:
    """Node 6: Synthesize evidence into chronological timeline and Post-Incident Review."""
    step_count = state.get("step_count", 0) + 1
    completed = list(state.get("completed_agents", []))
    failed = list(state.get("failed_agents", []))
    errors = dict(state.get("agent_errors", {}))

    agent = report_agent or ReportWriterAgent()
    res = await agent.execute(dict(state))

    final_report = res.get("final_report")
    if final_report:
        completed.append("ReportWriter")
        return {
            "step_count": step_count,
            "final_report": final_report,
            "completed_agents": completed,
        }
    else:
        failed.append("ReportWriter")
        err_msg = res.get("error_message", "ReportWriter synthesis failed")
        errors["ReportWriter"] = err_msg
        return {
            "step_count": step_count,
            "failed_agents": failed,
            "agent_errors": errors,
        }


async def validate_and_persist_node(state: InvestigationState) -> Dict[str, Any]:
    """Node 7: Final validation of report timeline ordering and status settlement."""
    final_report = state.get("final_report")
    failed_agents = state.get("failed_agents", [])

    if not final_report:
        return {"workflow_status": "FAILED"}

    # Validate timeline ordering
    timeline = final_report.timeline
    for i in range(len(timeline) - 1):
        if timeline[i].timestamp > timeline[i + 1].timestamp:
            logger.warning("Timeline ordering violation detected. Re-sorting chronologically.")
            timeline.sort(key=lambda x: x.timestamp)
            break

    # Determine final operational status
    if failed_agents:
        final_status = "PARTIAL"
    else:
        final_status = "COMPLETED"

    return {"workflow_status": final_status}
