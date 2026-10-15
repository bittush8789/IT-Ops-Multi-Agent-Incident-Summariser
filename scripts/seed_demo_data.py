"""Database seeding script to initialize sample incidents and pgvector historical knowledge."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from app.database.connection import get_session_factory
from app.database.models import Incident, IncidentKnowledge
from app.rag.embeddings import get_embedding_service


async def seed_data() -> None:
    """Populate database with sample incident and historical knowledge fixtures."""
    session_factory = get_session_factory()
    embedding_service = get_embedding_service()

    fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

    async with session_factory() as session:
        # 1. Seed Historical Incidents with Vector Embeddings
        hist_path = fixtures_dir / "historical_incidents.json"
        if hist_path.exists():
            with open(hist_path, "r", encoding="utf-8") as f:
                hist_records = json.load(f)

            print(f"Seeding {len(hist_records)} historical incident knowledge entries into pgvector...")
            for rec in hist_records:
                combined_text = f"Incident: {rec['title']}. Content: {rec['content']} Resolution: {rec['resolution']}"
                embedding = await embedding_service.get_embedding(combined_text)

                item = IncidentKnowledge(
                    content=rec["content"],
                    resolution=rec["resolution"],
                    embedding=embedding,
                    metadata_={
                        "title": rec["title"],
                        "incident_key": rec["source_incident_key"],
                        "service_name": rec.get("service_name"),
                        **rec.get("metadata", {}),
                    },
                )
                session.add(item)

        # 2. Seed a sample active incident ready for investigation
        now = datetime.now(timezone.utc)
        sample_incident = Incident(
            incident_key="INC-2026-1001",
            title="Payment Gateway Database Pool Starvation",
            description="Elevated HTTP 504 Gateway Timeout errors observed on /api/v1/checkout and /api/v1/refund. Database connection pool queue saturation suspected.",
            service_name="payment-gateway",
            severity="CRITICAL",
            status="OPEN",
            started_at=now,
        )
        session.add(sample_incident)

        await session.commit()
        print("Demo database seeding successfully completed.")


if __name__ == "__main__":
    asyncio.run(seed_data())
