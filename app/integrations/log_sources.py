"""Log source abstractions and file-backed implementations for incident log analysis."""

import abc
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class BaseLogSource(abc.ABC):
    """Abstract interface for log sources (e.g., Elasticsearch, Datadog, CloudWatch, Local File)."""

    @abc.abstractmethod
    async def fetch_logs(
        self,
        service_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Fetch raw log entries matching criteria."""
        pass


class FileLogSource(BaseLogSource):
    """
    File-backed log source supporting JSON log files.
    Allows offline POC execution using realistic incident log exports.
    """

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    async def fetch_logs(
        self,
        service_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Read and parse logs from local JSON file."""
        if not self.file_path.exists():
            logger.warning("Log source file does not exist: %s. Returning synthetic fallback.", self.file_path)
            return self._fallback_synthetic_logs(service_name)

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            logs = data if isinstance(data, list) else data.get("logs", [])
            filtered: List[Dict[str, Any]] = []

            for idx, entry in enumerate(logs):
                # Service filter
                entry_service = entry.get("service") or entry.get("service_name")
                if service_name and entry_service and service_name.lower() not in entry_service.lower():
                    continue

                # Parse timestamp if available
                ts_str = entry.get("timestamp") or entry.get("@timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if start_time and ts < start_time:
                            continue
                        if end_time and ts > end_time:
                            continue
                    except ValueError:
                        pass

                # Attach source file reference for auditability
                entry_copy = dict(entry)
                if "evidence_reference" not in entry_copy:
                    entry_copy["evidence_reference"] = f"{self.file_path.name}:L{idx + 1}"

                filtered.append(entry_copy)
                if len(filtered) >= limit:
                    break

            return filtered
        except Exception as exc:
            logger.error("Failed to load or parse log file %s: %s", self.file_path, str(exc))
            return self._fallback_synthetic_logs(service_name)

    def _fallback_synthetic_logs(self, service_name: Optional[str]) -> List[Dict[str, Any]]:
        """Fallback synthetic logs if fixture file is missing."""
        svc = service_name or "payment-service"
        now = datetime.now(timezone.utc)
        return [
            {
                "timestamp": now.isoformat(),
                "service": svc,
                "level": "ERROR",
                "http_status": 504,
                "error_type": "TIMEOUT",
                "message": "Gateway timeout connecting to upstream database pool (timeout=30000ms)",
                "exception_class": "ConnectionPoolTimeoutException",
                "evidence_reference": "synthetic_fallback:L1",
            },
            {
                "timestamp": now.isoformat(),
                "service": svc,
                "level": "FATAL",
                "http_status": 500,
                "error_type": "HTTP_5XX",
                "message": "HTTP 500 Internal Server Error: Database connection refused on port 5432",
                "exception_class": "DatabaseConnectionRefused",
                "evidence_reference": "synthetic_fallback:L2",
            },
        ]


def get_log_source(settings: Optional[Settings] = None, custom_path: Optional[str] = None) -> BaseLogSource:
    """Factory to retrieve configured log source."""
    cfg = settings or get_settings()
    path = custom_path or cfg.LOG_FIXTURE_PATH
    return FileLogSource(path)
