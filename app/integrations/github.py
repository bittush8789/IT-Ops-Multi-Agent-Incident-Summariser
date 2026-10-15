"""GitHub API client abstraction and fixture-backed mock implementation."""

import abc
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

from app.config import Settings, get_settings
from app.schemas.agent_findings import ChangeItem

logger = logging.getLogger(__name__)


class BaseGitHubClient(abc.ABC):
    """Abstract interface for source control and deployment telemetry retrieval."""

    @abc.abstractmethod
    async def get_recent_changes(
        self,
        repository: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 20,
    ) -> List[ChangeItem]:
        """Fetch recent commits and deployment records for the specified repository."""
        pass


class MockGitHubClient(BaseGitHubClient):
    """
    Mock GitHub client backed by a local JSON fixture file.
    Permits offline development and deterministic testing without GitHub API tokens or network access.
    """

    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)

    async def get_recent_changes(
        self,
        repository: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 20,
    ) -> List[ChangeItem]:
        """Read and parse changes from fixture file with time window filtering."""
        if not self.fixture_path.exists():
            logger.warning("GitHub fixture file missing: %s. Using default synthetic changes.", self.fixture_path)
            return self._fallback_synthetic_changes(repository)

        try:
            with open(self.fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_items = data if isinstance(data, list) else data.get("changes", [])
            changes: List[ChangeItem] = []

            for item in raw_items:
                ts_str = item.get("timestamp")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)

                if since and ts < since:
                    continue
                if until and ts > until:
                    continue

                changes.append(
                    ChangeItem(
                        commit_id=item.get("commit_id", "c0ffee1"),
                        author=item.get("author", "developer@company.internal"),
                        message=item.get("message", "Routine update"),
                        timestamp=ts,
                        repository=item.get("repository", repository),
                        files_changed=item.get("files_changed", []),
                        deployment_env=item.get("deployment_env", "production"),
                        deployment_status=item.get("deployment_status", "SUCCESS"),
                        relation_to_incident=item.get("relation_to_incident", "SUSPECT"),
                        evidence_reference=item.get(
                            "evidence_reference",
                            f"git://{repository}/commit/{item.get('commit_id', 'c0ffee1')}",
                        ),
                    )
                )

                if len(changes) >= limit:
                    break

            return changes
        except Exception as exc:
            logger.error("Error reading GitHub fixture %s: %s", self.fixture_path, str(exc))
            return self._fallback_synthetic_changes(repository)

    def _fallback_synthetic_changes(self, repository: str) -> List[ChangeItem]:
        """Synthetic changes when fixture is absent."""
        now = datetime.now(timezone.utc)
        return [
            ChangeItem(
                commit_id="8f92bd3",
                author="alex.dev@corp.internal",
                message="fix(pool): reduce default db pool timeout from 60s to 5s",
                timestamp=now,
                repository=repository,
                files_changed=["config/database.yaml", "src/connection_pool.py"],
                deployment_env="production",
                deployment_status="SUCCESS",
                relation_to_incident="SUSPECT",
                evidence_reference=f"git://{repository}/commit/8f92bd3",
            ),
            ChangeItem(
                commit_id="4b71ae9",
                author="sarah.infra@corp.internal",
                message="chore(k8s): bump replica count to 12 in deployment manifest",
                timestamp=now,
                repository=repository,
                files_changed=["k8s/deployment.yaml"],
                deployment_env="production",
                deployment_status="SUCCESS",
                relation_to_incident="COINCIDENT",
                evidence_reference=f"git://{repository}/commit/4b71ae9",
            ),
        ]


class GitHubRestClient(BaseGitHubClient):
    """Live GitHub REST API client using httpx. Used when GITHUB_USE_MOCK=False."""

    def __init__(self, token: Optional[str] = None, timeout: float = 10.0) -> None:
        self.token = token
        self.timeout = timeout
        self.base_url = "https://api.github.com"

    async def get_recent_changes(
        self,
        repository: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 20,
    ) -> List[ChangeItem]:
        """Fetch commits from GitHub REST API."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "IT-Ops-Multi-Agent-Incident-Summariser",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        params: Dict[str, Any] = {"per_page": min(limit, 100)}
        if since:
            params["since"] = since.isoformat()
        if until:
            params["until"] = until.isoformat()

        url = f"{self.base_url}/repos/{repository}/commits"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                commits = response.json()

                changes: List[ChangeItem] = []
                for c in commits:
                    commit_data = c.get("commit", {})
                    author_data = commit_data.get("author", {})
                    sha = c.get("sha", "")[:7]
                    ts_str = author_data.get("date")
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)

                    changes.append(
                        ChangeItem(
                            commit_id=sha,
                            author=author_data.get("name", "Unknown"),
                            message=commit_data.get("message", "").split("\n")[0],
                            timestamp=ts,
                            repository=repository,
                            files_changed=[],
                            deployment_env="production",
                            deployment_status="SUCCESS",
                            relation_to_incident="SUSPECT",
                            evidence_reference=f"https://github.com/{repository}/commit/{sha}",
                        )
                    )
                return changes
            except Exception as exc:
                logger.error("GitHub API error for repo %s: %s. Falling back to empty list.", repository, str(exc))
                return []


def get_github_client(settings: Optional[Settings] = None) -> BaseGitHubClient:
    """Factory to return configured GitHub client (mock by default)."""
    cfg = settings or get_settings()
    if cfg.GITHUB_USE_MOCK or not cfg.GITHUB_TOKEN:
        return MockGitHubClient(cfg.GITHUB_FIXTURE_PATH)
    return GitHubRestClient(token=cfg.GITHUB_TOKEN)
