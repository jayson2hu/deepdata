from __future__ import annotations

from collections.abc import Callable, Container
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.models import OutboxEvent

Publisher = Callable[[str, dict[str, Any], str], None]


def emit(session: Session, topic: str, payload: dict[str, Any], idempotency_key: str) -> bool:
    existing = session.scalar(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return False
    event = OutboxEvent(topic=topic, payload=payload, idempotency_key=idempotency_key)
    session.add(event)
    session.flush()
    return True


def relay_once(
    session: Session,
    publisher: Publisher,
    *,
    already_published: Container[str] | None = None,
) -> int:
    events = session.scalars(
        select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id)
    ).all()
    count = 0
    for event in events:
        if already_published is not None and event.idempotency_key in already_published:
            event.published_at = datetime.now(UTC)
            continue
        publisher(event.topic, event.payload, event.idempotency_key)
        event.published_at = datetime.now(UTC)
        count += 1
    session.flush()
    return count
