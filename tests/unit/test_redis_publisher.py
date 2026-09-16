from __future__ import annotations

import json
from typing import cast

import pytest
from fakeredis import FakeRedis
from redis.exceptions import ConnectionError, ResponseError
from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.models import OutboxEvent
from core_data.events.outbox import emit, relay_once
from core_data.events.publishers import RedisLike, RedisStreamPublisher


@pytest.fixture()
def redis_client() -> FakeRedis:
    return FakeRedis(decode_responses=True)


def test_redis_publisher_atomically_deduplicates(redis_client: FakeRedis) -> None:
    publisher = RedisStreamPublisher(cast(RedisLike, redis_client), queue_name="events")

    publisher("content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    publisher("content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")

    assert redis_client.llen("events") == 1
    envelope = json.loads(redis_client.lindex("events", 0))
    assert envelope == {
        "topic": "content.ingested",
        "payload": {"content_id": 1, "lang": "en"},
        "idempotency_key": "content.ingested:1",
    }
    assert publisher.has_published("content.ingested:1")
    assert 0 < redis_client.ttl("codepick:l0:published:content.ingested:1") <= 7 * 24 * 3600
    assert publisher.already_published() == set()


def test_failed_enqueue_keeps_outbox_pending_and_can_retry(
    redis_client: FakeRedis, session: Session,
) -> None:
    publisher = RedisStreamPublisher(cast(RedisLike, redis_client), queue_name="events")
    emit(session, "content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    session.commit()
    redis_client.set("events", "a string cannot receive RPUSH")

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        relay_once(session, publisher)
    session.rollback()

    event = session.scalar(select(OutboxEvent))
    assert event is not None and event.published_at is None
    assert not publisher.has_published("content.ingested:1")
    assert redis_client.get("events") == "a string cannot receive RPUSH"

    redis_client.delete("events")
    assert relay_once(session, publisher) == 1
    session.commit()
    assert event.published_at is not None
    assert redis_client.llen("events") == 1
    assert publisher.has_published("content.ingested:1")


def test_lost_redis_response_retries_without_duplicate(
    redis_client: FakeRedis, session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = RedisStreamPublisher(cast(RedisLike, redis_client), queue_name="events")
    emit(session, "content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    session.commit()
    original_eval = redis_client.eval

    def lose_response(script: str, numkeys: int, *args: str | int) -> object:
        original_eval(script, numkeys, *args)
        raise ConnectionError("connection lost after Redis accepted the event")

    monkeypatch.setattr(redis_client, "eval", lose_response)
    with pytest.raises(ConnectionError, match="connection lost"):
        relay_once(session, publisher)
    session.rollback()

    event = session.scalar(select(OutboxEvent))
    assert event is not None and event.published_at is None
    assert redis_client.llen("events") == 1
    assert publisher.has_published("content.ingested:1")

    monkeypatch.setattr(redis_client, "eval", original_eval)
    assert relay_once(session, publisher) == 1
    session.commit()
    assert event.published_at is not None
    assert redis_client.llen("events") == 1


def test_invalid_payload_does_not_mark_event_published(redis_client: FakeRedis) -> None:
    publisher = RedisStreamPublisher(cast(RedisLike, redis_client), queue_name="events")

    with pytest.raises(TypeError):
        publisher("content.ingested", {"not_json": object()}, "content.ingested:1")

    assert not publisher.has_published("content.ingested:1")
    assert redis_client.llen("events") == 0
    publisher("content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    assert redis_client.llen("events") == 1


@pytest.mark.parametrize("ttl_sec", [0, -1, 2**63, True, 1.5])
def test_invalid_ttl_is_rejected_before_writing(redis_client: FakeRedis, ttl_sec: int) -> None:
    with pytest.raises(ValueError, match="ttl_sec"):
        RedisStreamPublisher(cast(RedisLike, redis_client), ttl_sec=ttl_sec)
    assert redis_client.dbsize() == 0


def test_queue_and_marker_cannot_share_a_key(redis_client: FakeRedis) -> None:
    publisher = RedisStreamPublisher(
        cast(RedisLike, redis_client), queue_name="published:event", key_prefix="published",
    )
    with pytest.raises(ValueError, match="different"):
        publisher("content.ingested", {"content_id": 1, "lang": "en"}, "event")
    assert redis_client.dbsize() == 0
