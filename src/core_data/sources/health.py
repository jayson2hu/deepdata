from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core_data.db.models import SourceHealth


def mark_attempt(session: Session, source_id: int) -> SourceHealth:
    health = session.get(SourceHealth, source_id)
    if health is None:
        health = SourceHealth(source_id=source_id, status="unknown")
        session.add(health)
        session.flush()
    health.last_attempt_at = datetime.now(UTC)
    return health


def mark_success(session: Session, source_id: int, *, empty: bool) -> SourceHealth:
    health = mark_attempt(session, source_id)
    health.last_ok_at = datetime.now(UTC)
    health.fail_count = 0
    health.empty_streak = health.empty_streak + 1 if empty else 0
    health.status = "empty" if empty else "ok"
    health.note = None
    session.flush()
    return health


def mark_failure(session: Session, source_id: int, error: str) -> SourceHealth:
    health = mark_attempt(session, source_id)
    health.fail_count += 1
    health.status = "failed"
    health.note = error[:1000]
    session.flush()
    return health
