"""Langfuse observability integration for AI agent execution, model calls, and traces."""

import logging
import uuid
from typing import Any, Dict, Optional
from app.config import get_settings

logger = logging.getLogger(__name__)


class LangfuseTracker:
    """Wrapper around Langfuse SDK with safe no-op fallbacks when disabled."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.enabled = (
            self.settings.LANGFUSE_ENABLED
            and bool(self.settings.LANGFUSE_PUBLIC_KEY)
            and not self.settings.LANGFUSE_PUBLIC_KEY.startswith("pk-lf-placeholder")
        )
        self._client = None
        if self.enabled:
            try:
                from langfuse import Langfuse
                self._client = Langfuse(
                    public_key=self.settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=self.settings.LANGFUSE_SECRET_KEY,
                    host=self.settings.LANGFUSE_HOST,
                )
                logger.info("Langfuse observability enabled.")
            except Exception as exc:
                logger.warning("Failed to initialize Langfuse client: %s. Disabling.", str(exc))
                self.enabled = False

    def create_trace(
        self,
        name: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new root trace for an incident investigation."""
        trace_id = str(uuid.uuid4())
        if not self.enabled or not self._client:
            return trace_id

        try:
            self._client.trace(
                id=trace_id,
                name=name,
                session_id=session_id,
                metadata=metadata or {},
            )
        except Exception as exc:
            logger.warning("Error creating Langfuse trace: %s", str(exc))

        return trace_id

    def record_generation(
        self,
        trace_id: str,
        name: str,
        model: str,
        input_messages: Any,
        output_text: str,
        token_usage: Optional[Dict[str, int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an LLM generation event."""
        if not self.enabled or not self._client:
            return

        try:
            self._client.generation(
                trace_id=trace_id,
                name=name,
                model=model,
                input=input_messages,
                output=output_text,
                usage=token_usage or {},
                metadata=metadata or {},
            )
        except Exception as exc:
            logger.warning("Error recording Langfuse generation: %s", str(exc))

    def record_agent_span(
        self,
        trace_id: str,
        agent_name: str,
        status: str,
        duration_seconds: float,
        steps_used: int,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an individual agent execution span."""
        if not self.enabled or not self._client:
            return

        try:
            span = self._client.span(
                trace_id=trace_id,
                name=f"agent:{agent_name}",
                metadata={
                    "status": status,
                    "duration_seconds": duration_seconds,
                    "steps_used": steps_used,
                    "error": error_message,
                    **(metadata or {}),
                },
            )
            span.end()
        except Exception as exc:
            logger.warning("Error recording Langfuse agent span: %s", str(exc))

    def flush(self) -> None:
        """Flush pending events to Langfuse."""
        if self.enabled and self._client:
            try:
                self._client.flush()
            except Exception:
                pass


_langfuse_tracker_instance = None


def get_langfuse_tracker() -> LangfuseTracker:
    """Return singleton LangfuseTracker."""
    global _langfuse_tracker_instance
    if _langfuse_tracker_instance is None:
        _langfuse_tracker_instance = LangfuseTracker()
    return _langfuse_tracker_instance
