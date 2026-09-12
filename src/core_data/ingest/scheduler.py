from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.models import Source, SourceHealth


def due_sources(session: Session, *, now: datetime | None = None) -> list[Source]:
    current = now or datetime.now(UTC)
    sources = session.scalars(select(Source).where(Source.enabled.is_(True))).all()
    due: list[Source] = []
    for source in sources:
        interval = int(source.crawl_config.get("interval_min") or 60)
        health = session.get(SourceHealth, source.id)
        if health is None or health.last_attempt_at is None:
            due.append(source)
            continue
        last = health.last_attempt_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if current - last >= timedelta(minutes=interval):
            due.append(source)
    return due
