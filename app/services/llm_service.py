"""LLM Service integration supporting Google Gemini API with structured outputs and offline mock fallback."""

import abc
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.observability.langfuse_tracker import get_langfuse_tracker
from app.schemas.agent_findings import (
    ChangeAnalystResult,
    ChangeItem,
    ErrorGroup,
    LogAnalystResult,
    LogFindingItem,
)
from app.schemas.report import (
    ActionItem,
    IncidentReportBase,
    PostIncidentReview,
    RootCauseHypothesis,
    TimelineEntry,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseLLMService(abc.ABC):
    """Abstract interface for LLM operations."""

    @abc.abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        trace_id: Optional[str] = None,
    ) -> str:
        """Generate unstructured text response."""
        pass

    @abc.abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema_class: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        trace_id: Optional[str] = None,
    ) -> T:
        """Generate structured response validated against a Pydantic model."""
        pass


class GeminiLLMService(BaseLLMService):
    """Production Google Gemini LLM implementation with structured JSON generation."""

    def __init__(self, api_key: str, model_name: str = "gemini-3.8-flash") -> None:
        self.api_key = api_key
        self.model_name = model_name
        self._configured = False

    def _ensure_configured(self) -> None:
        if not self._configured:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._configured = True

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        trace_id: Optional[str] = None,
    ) -> str:
        self._ensure_configured()
        import google.generativeai as genai

        try:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction,
                generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
            )
            response = await model.generate_content_async(prompt)
            output_text = response.text or ""

            if trace_id:
                tracker = get_langfuse_tracker()
                tracker.record_generation(
                    trace_id=trace_id,
                    name=f"gemini_text:{self.model_name}",
                    model=self.model_name,
                    input_messages=prompt[:500],
                    output_text=output_text[:500],
                )

            return output_text
        except Exception as exc:
            masked_error = str(exc).replace(self.api_key, "[REDACTED_API_KEY]")
            logger.error("Gemini text generation failed: %s", masked_error)
            raise RuntimeError(f"Gemini API error: {masked_error}") from exc

    async def generate_structured(
        self,
        prompt: str,
        schema_class: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        trace_id: Optional[str] = None,
    ) -> T:
        self._ensure_configured()
        import google.generativeai as genai

        # Instruct model to return pure JSON schema matching Pydantic definition
        schema_json = json.dumps(schema_class.model_json_schema(), indent=2)
        full_system = (system_instruction or "") + f"\nYou MUST respond with valid JSON matching this schema:\n{schema_json}"

        try:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=full_system,
                generation_config={
                    "temperature": temperature,
                    "response_mime_type": "application/json",
                },
            )
            response = await model.generate_content_async(prompt)
            raw_text = response.text or "{}"

            if trace_id:
                tracker = get_langfuse_tracker()
                tracker.record_generation(
                    trace_id=trace_id,
                    name=f"gemini_structured:{schema_class.__name__}",
                    model=self.model_name,
                    input_messages=prompt[:500],
                    output_text=raw_text[:500],
                )

            return schema_class.model_validate_json(raw_text)
        except ValidationError as val_err:
            logger.error("Structured schema validation failed for %s: %s", schema_class.__name__, str(val_err))
            raise
        except Exception as exc:
            masked_error = str(exc).replace(self.api_key, "[REDACTED_API_KEY]")
            logger.error("Gemini structured call failed: %s", masked_error)
            raise RuntimeError(f"Gemini API error: {masked_error}") from exc


class MockLLMService(BaseLLMService):
    """
    Mock LLM Service for offline development, local demos, and deterministic unit tests.
    Produces valid Pydantic models with plausible incident findings without external network calls.
    """

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        trace_id: Optional[str] = None,
    ) -> str:
        return "Investigation plan created. Dispatched Log Analyst and Change Analyst tasks."

    async def generate_structured(
        self,
        prompt: str,
        schema_class: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        trace_id: Optional[str] = None,
    ) -> T:
        now = datetime.now(timezone.utc)

        # Handle Log Analyst output schema
        if schema_class == LogAnalystResult:
            mock_log = LogAnalystResult(
                status="COMPLETED",
                earliest_error_timestamp=now,
                subsequent_symptoms=[
                    "Connection pool exhaustion on primary PostgreSQL cluster",
                    "HTTP 504 Gateway Timeout across /api/v1/checkout endpoints",
                    "Circuit breaker tripped on payment-gateway downstream client",
                ],
                error_groups=[
                    ErrorGroup(
                        service="payment-gateway",
                        error_type="TIMEOUT",
                        sample_message="Upstream database pool acquisition timeout after 30000ms",
                        total_occurrences=142,
                        first_seen=now,
                        last_seen=now,
                        affected_endpoints=["/api/v1/checkout", "/api/v1/refund"],
                    ),
                    ErrorGroup(
                        service="payment-gateway",
                        error_type="HTTP_5XX",
                        sample_message="500 Internal Server Error: Database pool exhausted",
                        total_occurrences=89,
                        first_seen=now,
                        last_seen=now,
                        affected_endpoints=["/api/v1/checkout"],
                    ),
                ],
                findings=[
                    LogFindingItem(
                        timestamp=now,
                        service="payment-gateway",
                        error_type="TIMEOUT",
                        message="ConnectionPoolTimeout: Queue wait time exceeded 30000ms",
                        http_status=504,
                        exception_class="PoolTimeoutException",
                        count=142,
                        evidence_reference="incident_logs.json:L45",
                        is_fact=True,
                    ),
                    LogFindingItem(
                        timestamp=now,
                        service="payment-gateway",
                        error_type="HTTP_5XX",
                        message="HTTP 500: Database connection closed unexpectedly",
                        http_status=500,
                        exception_class="ConnectionResetError",
                        count=89,
                        evidence_reference="incident_logs.json:L88",
                        is_fact=True,
                    ),
                ],
                raw_log_count=231,
                errors_detected=231,
                inferred_root_cause_notes="Observed database connection pool starvation following abrupt connection timeout decrease.",
            )
            return mock_log  # type: ignore

        # Handle Change Analyst output schema
        if schema_class == ChangeAnalystResult:
            mock_change = ChangeAnalystResult(
                status="COMPLETED",
                relevant_changes=[
                    ChangeItem(
                        commit_id="8f92bd3",
                        author="alex.dev@corp.internal",
                        message="fix(pool): reduce default db pool timeout from 60s to 5s",
                        timestamp=now,
                        repository="enterprise-org/payment-gateway",
                        files_changed=["config/database.yaml", "src/connection_pool.py"],
                        deployment_env="production",
                        deployment_status="SUCCESS",
                        relation_to_incident="SUSPECT",
                        evidence_reference="git://enterprise-org/payment-gateway/commit/8f92bd3",
                    ),
                    ChangeItem(
                        commit_id="4b71ae9",
                        author="sarah.infra@corp.internal",
                        message="chore(k8s): bump replica count to 12 in deployment manifest",
                        timestamp=now,
                        repository="enterprise-org/payment-gateway",
                        files_changed=["k8s/deployment.yaml"],
                        deployment_env="production",
                        deployment_status="SUCCESS",
                        relation_to_incident="COINCIDENT",
                        evidence_reference="git://enterprise-org/payment-gateway/commit/4b71ae9",
                    ),
                ],
                change_count=2,
                deployments_detected=2,
                correlation_notes="Commit 8f92bd3 reduced pool timeout just prior to the first reported timeout error.",
            )
            return mock_change  # type: ignore

        # Handle Incident Report Base schema
        if schema_class == IncidentReportBase:
            timeline = [
                TimelineEntry(
                    timestamp=now,
                    event_type="DEPLOYMENT",
                    source="ChangeAnalyst",
                    description="Commit 8f92bd3 deployed reducing DB pool acquisition timeout from 60s to 5s",
                    evidence_reference="git://enterprise-org/payment-gateway/commit/8f92bd3",
                    is_inferred=False,
                ),
                TimelineEntry(
                    timestamp=now,
                    event_type="ERROR_SURGE",
                    source="LogAnalyst",
                    description="First ConnectionPoolTimeoutException observed in payment-gateway logs",
                    evidence_reference="incident_logs.json:L45",
                    is_inferred=False,
                ),
                TimelineEntry(
                    timestamp=now,
                    event_type="ALERT",
                    source="Monitoring",
                    description="HTTP 504 Gateway Timeout alert triggered for /api/v1/checkout",
                    evidence_reference="incident_logs.json:L88",
                    is_inferred=False,
                ),
            ]
            root_causes = [
                RootCauseHypothesis(
                    hypothesis="Aggressive reduction of database connection pool timeout (from 60s to 5s) combined with horizontal pod scaling saturated database connection slots, resulting in cascading pool acquisition timeouts.",
                    likelihood="HIGH",
                    supporting_evidence=[
                        "Commit 8f92bd3 modified config/database.yaml timeout setting 12 minutes before first error (git://enterprise-org/payment-gateway/commit/8f92bd3)",
                        "142 ConnectionPoolTimeout exceptions logged starting immediately after deploy (incident_logs.json:L45)",
                    ],
                    contradicting_evidence=[],
                    unknowns=["Database CPU and IOPS metrics at the time of connection spike"],
                )
            ]
            recs = [
                ActionItem(
                    title="Roll back database pool timeout setting",
                    description="Revert config/database.yaml timeout parameter to 60s",
                    priority="P0",
                    owner_team="SRE",
                    action_type="REMEDIATION",
                ),
                ActionItem(
                    title="Implement load testing in CI/CD for connection pool tuning",
                    description="Add automated canary regression test validating database connection behavior under concurrency",
                    priority="P1",
                    owner_team="Platform Engineering",
                    action_type="PREVENTION",
                ),
            ]
            pir = PostIncidentReview(
                summary="The payment-gateway service suffered an elevated error rate (HTTP 504 and 500) caused by connection pool starvation following a configuration change.",
                impact="Customer checkout requests failed with HTTP 504 Gateway Timeout during the incident window.",
                contributing_factors=[
                    "Configuration change commit 8f92bd3 lowered pool timeout",
                    "Simultaneous replica scale-out increased concurrent connection contention",
                ],
                lessons_learned=[
                    "Canary deployments should be mandated for connection pool configuration updates",
                    "Monitoring thresholds on pool acquisition latency should be made stricter",
                ],
                timeline=timeline,
                follow_up_actions=recs,
            )
            mock_report = IncidentReportBase(
                executive_summary="On-call investigation determined that payment-gateway experienced cascading timeouts triggered by a production configuration change (commit 8f92bd3) which reduced database pool timeout thresholds under heavy traffic.",
                impact_summary="Checkout and refund transactions were degraded with 142 timeout errors and 89 server errors across the payment gateway service.",
                timeline=timeline,
                root_cause_hypotheses=root_causes,
                recommendations=recs,
                post_incident_review=pir,
                confidence_notes="High confidence based on exact temporal match between commit 8f92bd3 and log error surge (incident_logs.json:L45). No missing specialist evidence.",
            )
            return mock_report  # type: ignore

        # Fallback empty construction if another schema requested
        return schema_class.model_construct()


def get_llm_service(settings: Optional[Settings] = None) -> BaseLLMService:
    """Factory returning configured LLM service (Gemini if key configured, otherwise Mock)."""
    cfg = settings or get_settings()
    if cfg.GEMINI_API_KEY and cfg.GEMINI_API_KEY.strip() and not cfg.GEMINI_API_KEY.startswith("your_"):
        return GeminiLLMService(api_key=cfg.GEMINI_API_KEY, model_name=cfg.GEMINI_MODEL)
    return MockLLMService()
