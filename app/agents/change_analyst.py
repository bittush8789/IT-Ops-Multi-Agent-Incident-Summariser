"""Change Analyst Agent: Analyzes git commits, PRs, and deployments for incident correlation."""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.integrations.github import BaseGitHubClient, get_github_client
from app.prompts.change_analyst_prompts import (
    CHANGE_ANALYST_ANALYSIS_PROMPT,
    CHANGE_ANALYST_SYSTEM_PROMPT,
)
from app.schemas.agent_findings import (
    ChangeAnalystResult,
    ChangeItem,
)
from app.services.llm_service import BaseLLMService, get_llm_service

logger = logging.getLogger(__name__)


class ChangeAnalystAgent(BaseAgent):
    """
    Change Analyst Agent evaluates recent commits and deployments:
    - Extracts author, commit SHA, message, files changed
    - Compares commit timestamp against incident timeline
    - Classifies temporal relation (PRE_INCIDENT, COINCIDENT, POST_INCIDENT)
    - Distinguishes potential correlation without premature root-cause declaration
    """

    def __init__(
        self,
        github_client: Optional[BaseGitHubClient] = None,
        llm_service: Optional[BaseLLMService] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(name="ChangeAnalyst", timeout_seconds=timeout_seconds)
        self.github_client = github_client or get_github_client()
        self.llm_service = llm_service or get_llm_service()

    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch changes, analyze temporal relation, and return structured ChangeAnalystResult."""
        repo = state.get("github_repo") or self.settings.GITHUB_REPO
        incident_key = state.get("incident_key", "UNKNOWN")
        trace_id = state.get("trace_id")
        started_at = state.get("started_at")

        # 1. Fetch recent changes from GitHub client
        changes: List[ChangeItem] = await self.github_client.get_recent_changes(
            repository=repo,
            limit=10,
        )

        if not changes:
            logger.info("No git changes found for repository %s", repo)
            empty_result = ChangeAnalystResult(
                status="COMPLETED",
                relevant_changes=[],
                change_count=0,
                deployments_detected=0,
                correlation_notes="No commits or deployment events retrieved in the specified window.",
            )
            return {"change_result": empty_result}

        # 2. Determine temporal correlation for each change
        deployments_count = 0
        incident_time = started_at if isinstance(started_at, datetime) else None
        if isinstance(started_at, str):
            try:
                incident_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            except ValueError:
                incident_time = None

        for ch in changes:
            if ch.deployment_status:
                deployments_count += 1

            if incident_time:
                diff_seconds = (ch.timestamp - incident_time).total_seconds()
                if diff_seconds < -7200:
                    ch.relation_to_incident = "UNRELATED"
                elif -7200 <= diff_seconds <= 0:
                    ch.relation_to_incident = "PRE_INCIDENT"
                elif 0 < diff_seconds <= 3600:
                    ch.relation_to_incident = "COINCIDENT"
                else:
                    ch.relation_to_incident = "POST_INCIDENT"

        # 3. Formulate LLM prompt for structured correlation analysis
        prompt = CHANGE_ANALYST_ANALYSIS_PROMPT.format(
            incident_key=incident_key,
            service_name=state.get("service_name", "Unknown"),
            title=state.get("title", ""),
            started_at=str(started_at),
            raw_changes=json.dumps([c.model_dump(mode="json") for c in changes], default=str, indent=2),
        )

        try:
            llm_result: ChangeAnalystResult = await self.llm_service.generate_structured(
                prompt=prompt,
                schema_class=ChangeAnalystResult,
                system_instruction=CHANGE_ANALYST_SYSTEM_PROMPT,
                trace_id=trace_id,
            )
            llm_result.change_count = len(changes)
            llm_result.deployments_detected = deployments_count
            return {"change_result": llm_result}
        except Exception as exc:
            logger.warning("LLM change analysis failed, falling back to deterministic extraction: %s", str(exc))
            fallback_result = ChangeAnalystResult(
                status="COMPLETED",
                relevant_changes=changes,
                change_count=len(changes),
                deployments_detected=deployments_count,
                correlation_notes=f"Identified {len(changes)} changes. Found {deployments_count} deployments. Temporal correlation assigned based on commit timestamps.",
            )
            return {"change_result": fallback_result}
