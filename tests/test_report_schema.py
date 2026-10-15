"""Tests for Pydantic schema validation of incident reports and PIR artifacts."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.report import (
    ActionItem,
    IncidentReportBase,
    PostIncidentReview,
    RootCauseHypothesis,
    TimelineEntry,
)


def test_timeline_entry_validation():
    """Verify TimelineEntry requires timestamp, event_type, source, and evidence_reference."""
    now = datetime.now(timezone.utc)
    entry = TimelineEntry(
        timestamp=now,
        event_type="DEPLOYMENT",
        source="ChangeAnalyst",
        description="Deployed commit 8f92bd3",
        evidence_reference="git://repo/commit/8f92bd3",
        is_inferred=False,
    )
    assert entry.event_type == "DEPLOYMENT"
    assert entry.is_inferred is False

    # Missing evidence reference must raise ValidationError
    with pytest.raises(ValidationError):
        TimelineEntry(
            timestamp=now,
            event_type="ALERT",
            source="Monitoring",
            description="Alert triggered",
            # evidence_reference omitted
        )


def test_incident_report_base_full_validation():
    """Verify complete IncidentReportBase schema serialization and round-trip."""
    now = datetime.now(timezone.utc)
    entry = TimelineEntry(
        timestamp=now,
        event_type="ERROR_SURGE",
        source="LogAnalyst",
        description="Pool timeout",
        evidence_reference="incident_logs.json:L22",
    )
    rc = RootCauseHypothesis(
        hypothesis="Connection pool starvation",
        likelihood="HIGH",
        supporting_evidence=["incident_logs.json:L22"],
        contradicting_evidence=[],
        unknowns=[],
    )
    action = ActionItem(
        title="Revert timeout",
        description="Revert config parameter to 60s",
        priority="P0",
        owner_team="SRE",
    )
    pir = PostIncidentReview(
        summary="Service degradation summary",
        impact="142 checkout timeouts",
        contributing_factors=["Config deployment"],
        lessons_learned=["Test timeouts in staging"],
        timeline=[entry],
        follow_up_actions=[action],
    )

    report = IncidentReportBase(
        executive_summary="Executive summary text",
        impact_summary="Impact summary text",
        timeline=[entry],
        root_cause_hypotheses=[rc],
        recommendations=[action],
        post_incident_review=pir,
        confidence_notes="High confidence based on exact evidence match",
    )

    dump = report.model_dump(mode="json")
    assert dump["executive_summary"] == "Executive summary text"
    assert len(dump["timeline"]) == 1
    assert dump["timeline"][0]["evidence_reference"] == "incident_logs.json:L22"
