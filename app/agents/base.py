"""Base class for all multi-agent components in the IT-Ops incident summariser."""

import abc
import asyncio
import logging
from typing import Any, Dict, Optional
from app.config import get_settings
from app.observability.langfuse_tracker import get_langfuse_tracker
from app.observability.telemetry import async_trace_span

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """Abstract base agent providing timeout handling, span tracing, and audit metrics."""

    def __init__(self, name: str, timeout_seconds: Optional[int] = None) -> None:
        self.name = name
        self.settings = get_settings()
        self.timeout_seconds = timeout_seconds or self.settings.AGENT_TIMEOUT_SECONDS

    @abc.abstractmethod
    async def _run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Internal agent execution logic to be overridden by concrete agent classes."""
        pass

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent with span tracing, timeout enforcement, and exception safety."""
        trace_id = state.get("trace_id")
        tracker = get_langfuse_tracker()
        start_time = asyncio.get_event_loop().time()

        async with async_trace_span(f"agent:{self.name}", {"agent.name": self.name}):
            try:
                # Enforce execution timeout per agent
                result = await asyncio.wait_for(
                    self._run(state),
                    timeout=float(self.timeout_seconds),
                )
                duration = asyncio.get_event_loop().time() - start_time
                if trace_id:
                    tracker.record_agent_span(
                        trace_id=trace_id,
                        agent_name=self.name,
                        status="COMPLETED",
                        duration_seconds=duration,
                        steps_used=1,
                    )
                return result
            except asyncio.TimeoutError:
                duration = asyncio.get_event_loop().time() - start_time
                error_msg = f"Agent {self.name} timed out after {self.timeout_seconds} seconds"
                logger.error(error_msg)
                if trace_id:
                    tracker.record_agent_span(
                        trace_id=trace_id,
                        agent_name=self.name,
                        status="TIMEOUT",
                        duration_seconds=duration,
                        steps_used=1,
                        error_message=error_msg,
                    )
                return {
                    "status": "TIMEOUT",
                    "error_message": error_msg,
                    "agent_name": self.name,
                }
            except Exception as exc:
                duration = asyncio.get_event_loop().time() - start_time
                error_msg = f"Agent {self.name} failed with error: {str(exc)}"
                logger.error(error_msg, exc_info=True)
                if trace_id:
                    tracker.record_agent_span(
                        trace_id=trace_id,
                        agent_name=self.name,
                        status="FAILED",
                        duration_seconds=duration,
                        steps_used=1,
                        error_message=error_msg,
                    )
                return {
                    "status": "FAILED",
                    "error_message": error_msg,
                    "agent_name": self.name,
                }
