"""Log Analyst Agent: Discovers error surges, HTTP 5xx anomalies, and exception patterns in logs."""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.integrations.log_sources import BaseLogSource, get_log_source
from app.prompts.log_analyst_prompts import (
    LOG_ANALYST_ANALYSIS_PROMPT,
    LOG_ANALYST_SYSTEM_PROMPT,
)
from app.schemas.agent_findings import (
    ErrorGroup,
    LogAnalystResult,
    LogFindingItem,
)
from app.services.llm_service import BaseLLMService, get_llm_service

logger = logging.getLogger(__name__)


class LogAnalystAgent(BaseAgent):
    """
    Log Analyst Agent analyzes structured and unstructured incident logs:
    - Filters 5xx, timeouts, resource exhaustion
    - Groups recurring errors by service and category
    - Identifies earliest failure timestamp
    - Generates evidence-backed structured findings
    """

    def __init__(
        self,
        log_source: Optional[BaseLogSource] = None,
        llm_service: Optional[BaseLLMService] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(name="LogAnalyst", timeout_seconds=timeout_seconds)
        self.log_source = log_source or get_log_source()
        self.llm_service = llm_service or get_llm_service()

    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch logs, process error patterns, and generate structured analysis."""
        service_name = state.get("service_name")
        incident_key = state.get("incident_key", "UNKNOWN")
        trace_id = state.get("trace_id")

        # 1. Fetch raw logs from log source
        raw_logs = await self.log_source.fetch_logs(
            service_name=service_name,
            limit=200,
        )

        if not raw_logs:
            logger.warning("No logs found for service %s", service_name)
            empty_result = LogAnalystResult(
                status="COMPLETED",
                findings=[],
                raw_log_count=0,
                errors_detected=0,
                inferred_root_cause_notes="No log entries retrieved from log source.",
            )
            return {"log_result": empty_result}

        # 2. Deterministic preprocessing: classify and group errors
        error_entries: List[Dict[str, Any]] = []
        error_groups_dict: Dict[str, Dict[str, Any]] = {}
        earliest_error_ts: Optional[datetime] = None

        for entry in raw_logs:
            status_code = entry.get("http_status")
            level = str(entry.get("level", "")).upper()
            err_type = entry.get("error_type") or "UNKNOWN"
            msg = entry.get("message", "")

            is_error = (
                (status_code and status_code >= 500)
                or level in ("ERROR", "FATAL", "CRITICAL")
                or any(keyword in msg.lower() for keyword in ["timeout", "exception", "refused", "exhausted", "failed"])
            )

            if is_error:
                error_entries.append(entry)
                ts_str = entry.get("timestamp")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)

                if earliest_error_ts is None or ts < earliest_error_ts:
                    earliest_error_ts = ts

                group_key = f"{entry.get('service', service_name)}:{err_type}"
                if group_key not in error_groups_dict:
                    error_groups_dict[group_key] = {
                        "service": entry.get("service", service_name or "unknown"),
                        "error_type": err_type,
                        "sample_message": msg,
                        "total_occurrences": 0,
                        "first_seen": ts,
                        "last_seen": ts,
                        "affected_endpoints": set(),
                    }

                group_data = error_groups_dict[group_key]
                group_data["total_occurrences"] += 1
                if ts < group_data["first_seen"]:
                    group_data["first_seen"] = ts
                if ts > group_data["last_seen"]:
                    group_data["last_seen"] = ts
                endpoint = entry.get("endpoint") or entry.get("path")
                if endpoint:
                    group_data["affected_endpoints"].add(endpoint)

        # 3. Request LLM structured analysis with extracted evidence
        prompt = LOG_ANALYST_ANALYSIS_PROMPT.format(
            incident_key=incident_key,
            service_name=service_name,
            title=state.get("title", ""),
            description=state.get("description", ""),
            started_at=state.get("started_at", "Unknown"),
            raw_logs=json.dumps(error_entries[:20], default=str, indent=2),
        )

        try:
            llm_result: LogAnalystResult = await self.llm_service.generate_structured(
                prompt=prompt,
                schema_class=LogAnalystResult,
                system_instruction=LOG_ANALYST_SYSTEM_PROMPT,
                trace_id=trace_id,
            )
            # Ensure deterministic metrics are faithfully updated
            llm_result.raw_log_count = len(raw_logs)
            llm_result.errors_detected = len(error_entries)
            if earliest_error_ts and not llm_result.earliest_error_timestamp:
                llm_result.earliest_error_timestamp = earliest_error_ts

            return {"log_result": llm_result}
        except Exception as exc:
            logger.warning("LLM log analysis failed, falling back to deterministic extraction: %s", str(exc))
            # Resilient fallback: build validated LogAnalystResult deterministically
            findings = [
                LogFindingItem(
                    timestamp=datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) if e.get("timestamp") else datetime.now(timezone.utc),
                    service=e.get("service", service_name or "unknown"),
                    error_type=e.get("error_type", "HTTP_5XX"),
                    message=e.get("message", "Error"),
                    http_status=e.get("http_status"),
                    exception_class=e.get("exception_class"),
                    count=1,
                    evidence_reference=e.get("evidence_reference", "log_stream:L0"),
                    is_fact=True,
                )
                for e in error_entries[:10]
            ]
            error_groups = [
                ErrorGroup(
                    service=g["service"],
                    error_type=g["error_type"],
                    sample_message=g["sample_message"],
                    total_occurrences=g["total_occurrences"],
                    first_seen=g["first_seen"],
                    last_seen=g["last_seen"],
                    affected_endpoints=list(g["affected_endpoints"]),
                )
                for g in error_groups_dict.values()
            ]
            fallback_result = LogAnalystResult(
                status="COMPLETED",
                earliest_error_timestamp=earliest_error_ts or datetime.now(timezone.utc),
                subsequent_symptoms=[f"{g.error_type} in {g.service}: {g.sample_message}" for g in error_groups[:3]],
                error_groups=error_groups,
                findings=findings,
                raw_log_count=len(raw_logs),
                errors_detected=len(error_entries),
                inferred_root_cause_notes="Analysis completed via deterministic log pattern extraction.",
            )
            return {"log_result": fallback_result}
