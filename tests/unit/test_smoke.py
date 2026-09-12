from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from core_data.db.models import OutboxEvent
from core_data.events.outbox import emit, relay_once


def test_relay_count_ignores_historical_published_events(session) -> None:  # type: ignore[no-untyped-def]
    historical = OutboxEvent(
        topic="content.ingested",
        payload={"content_id": 1, "lang": "en"},
        idempotency_key="content.ingested:historical",
        published_at=datetime.now(UTC),
    )
    session.add(historical)
    emit(session, "content.ingested", {"content_id": 2, "lang": "en"}, "content.ingested:2")

    pending_outbox_count = (
        session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        )
        or 0
    )
    total_outbox_count = session.scalar(select(func.count()).select_from(OutboxEvent)) or 0
    delivered: list[str] = []
    relayed = relay_once(session, lambda topic, payload, key: delivered.append(key))

    assert total_outbox_count == 2
    assert pending_outbox_count == 1
    assert relayed == pending_outbox_count
    assert delivered == ["content.ingested:2"]
