from __future__ import annotations

import pytest
from sqlalchemy import func, select

from core_data.db.models import OutboxEvent
from core_data.events.outbox import emit, relay_once


def test_emit_is_idempotent_by_key(session) -> None:  # type: ignore[no-untyped-def]
    assert emit(session, "content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    assert not emit(
        session, "content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1"
    )
    assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_relay_publishes_unpublished_once(session) -> None:  # type: ignore[no-untyped-def]
    emit(session, "content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    delivered: list[str] = []
    assert relay_once(session, lambda topic, payload, key: delivered.append(key)) == 1
    assert relay_once(session, lambda topic, payload, key: delivered.append(key)) == 0
    assert delivered == ["content.ingested:1"]


def test_relay_restart_skips_event_already_accepted_by_publisher(session) -> None:  # type: ignore[no-untyped-def]
    emit(session, "content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    session.commit()
    accepted: set[str] = set()

    def crash_after_publish(topic: str, payload: dict[str, object], key: str) -> None:
        del topic, payload
        accepted.add(key)
        raise RuntimeError("relay crashed before marking published")

    with pytest.raises(RuntimeError):
        relay_once(session, crash_after_publish)
    session.rollback()

    delivered: list[str] = []
    assert (
        relay_once(
            session,
            lambda topic, payload, key: delivered.append(key),
            already_published=accepted,
        )
        == 0
    )
    event = session.scalar(select(OutboxEvent))
    assert event is not None
    assert event.published_at is not None
    assert delivered == []
