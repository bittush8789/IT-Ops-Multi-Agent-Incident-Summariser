"""LangGraph workflow definition for the IT-Ops Multi-Agent Incident Summariser."""

from typing import Optional
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.change_analyst import ChangeAnalystAgent
from app.agents.log_analyst import LogAnalystAgent
from app.agents.report_writer import ReportWriterAgent
from app.agents.supervisor import SupervisorAgent
from app.graph.edges import route_after_log_analyst, route_from_supervisor
from app.graph.nodes import (
    change_analyst_node,
    log_analyst_node,
    rag_retrieval_node,
    report_writer_node,
    supervisor_node,
    validate_and_persist_node,
    validate_scope_node,
)
from app.graph.state import InvestigationState
from app.rag.retrieval import IncidentKnowledgeRetriever


def build_investigation_graph(
    supervisor_agent: Optional[SupervisorAgent] = None,
    log_agent: Optional[LogAnalystAgent] = None,
    change_agent: Optional[ChangeAnalystAgent] = None,
    report_agent: Optional[ReportWriterAgent] = None,
    retriever: Optional[IncidentKnowledgeRetriever] = None,
) -> CompiledStateGraph:
    """
    Construct, wire, and compile the multi-agent investigation workflow.
    Supports dependency injection for offline testing, mocked specialists, and isolated units.
    """
    workflow = StateGraph(InvestigationState)

    # 1. Register Nodes with bound dependencies
    workflow.add_node("validate_scope", validate_scope_node)

    async def _supervisor_wrapper(state: InvestigationState):
        return await supervisor_node(state, supervisor_agent=supervisor_agent)

    async def _log_wrapper(state: InvestigationState):
        return await log_analyst_node(state, log_agent=log_agent)

    async def _change_wrapper(state: InvestigationState):
        return await change_analyst_node(state, change_agent=change_agent)

    async def _rag_wrapper(state: InvestigationState):
        return await rag_retrieval_node(state, retriever=retriever)

    async def _report_wrapper(state: InvestigationState):
        return await report_writer_node(state, report_agent=report_agent)

    workflow.add_node("supervisor", _supervisor_wrapper)
    workflow.add_node("log_analyst", _log_wrapper)
    workflow.add_node("change_analyst", _change_wrapper)
    workflow.add_node("rag_retrieval", _rag_wrapper)
    workflow.add_node("report_writer", _report_wrapper)
    workflow.add_node("validate_and_persist", validate_and_persist_node)

    # 2. Wire Graph Edges and Conditional Branches
    workflow.set_entry_point("validate_scope")
    workflow.add_edge("validate_scope", "supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "log_analyst": "log_analyst",
            "rag_retrieval": "rag_retrieval",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "log_analyst",
        route_after_log_analyst,
        {
            "change_analyst": "change_analyst",
            "rag_retrieval": "rag_retrieval",
        },
    )

    workflow.add_edge("change_analyst", "rag_retrieval")
    workflow.add_edge("rag_retrieval", "report_writer")
    workflow.add_edge("report_writer", "validate_and_persist")
    workflow.add_edge("validate_and_persist", END)

    return workflow.compile()
