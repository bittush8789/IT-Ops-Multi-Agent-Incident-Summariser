"""Supervisor Agent: Orchestrates investigation planning, dispatching, and budget enforcement."""

import logging
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.prompts.supervisor_prompts import SUPERVISOR_PLAN_PROMPT, SUPERVISOR_SYSTEM_PROMPT
from app.services.llm_service import BaseLLMService, get_llm_service

logger = logging.getLogger(__name__)


class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent coordinates the investigation workflow:
    - Enforces max step budget
    - Creates structured investigation plan
    - Determines if Log and Change specialists need execution
    - Prevents duplicate specialist executions
    - Collects evidence and routes to Report Writer
    """

    def __init__(
        self,
        llm_service: Optional[BaseLLMService] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(name="Supervisor", timeout_seconds=timeout_seconds)
        self.llm_service = llm_service or get_llm_service()

    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate current graph state, increment step budget, and determine next action."""
        current_step = state.get("step_count", 0) + 1
        max_steps = state.get("max_steps", self.settings.MAX_WORKFLOW_STEPS)

        # Check step budget exhaustion
        if current_step > max_steps:
            logger.warning("Investigation step budget exhausted (%d/%d)", current_step, max_steps)
            return {
                "step_count": current_step,
                "workflow_status": "BUDGET_EXHAUSTED",
                "next_step": "end",
                "supervisor_notes": f"Terminated safely: maximum step budget of {max_steps} exhausted.",
            }

        # Check if plan already exists
        plan = state.get("investigation_plan")
        if not plan:
            # Generate structured initial plan
            prompt = SUPERVISOR_PLAN_PROMPT.format(
                incident_key=state.get("incident_key", "UNKNOWN"),
                title=state.get("title", ""),
                service_name=state.get("service_name", ""),
                severity=state.get("severity", "HIGH"),
                description=state.get("description", ""),
                started_at=state.get("started_at", "Unknown"),
            )
            plan = await self.llm_service.generate_text(
                prompt=prompt,
                system_instruction=SUPERVISOR_SYSTEM_PROMPT,
                trace_id=state.get("trace_id"),
            )

        # Determine specialists pending execution
        completed_agents: List[str] = list(state.get("completed_agents", []))
        log_done = "LogAnalyst" in completed_agents or state.get("log_result") is not None
        change_done = "ChangeAnalyst" in completed_agents or state.get("change_result") is not None
        report_done = "ReportWriter" in completed_agents or state.get("final_report") is not None

        next_step: str
        if not log_done or not change_done:
            # Dispatch parallel or sequential specialist tasks
            next_step = "dispatch_specialists"
        elif not report_done:
            # Specialists finished; proceed to historical RAG retrieval & report writing
            next_step = "synthesize_report"
        else:
            # Investigation complete
            next_step = "complete"

        return {
            "step_count": current_step,
            "investigation_plan": plan,
            "next_step": next_step,
        }
