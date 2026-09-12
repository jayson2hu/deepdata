from __future__ import annotations

import json

from core_data.events.publishers import RedisStreamPublisher


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.queues: dict[str, list[str]] = {}

    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None) -> object:
        del ex
        if nx and name in self.values:
            return None
        self.values[name] = value
        return True

    def rpush(self, name: str, value: str) -> object:
        self.queues.setdefault(name, []).append(value)
        return len(self.queues[name])

    def exists(self, name: str) -> int:
        return 1 if name in self.values else 0


def test_redis_publisher_uses_setnx_for_idempotency() -> None:
    redis = FakeRedis()
    publisher = RedisStreamPublisher(redis, queue_name="events")

    publisher("content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")
    publisher("content.ingested", {"content_id": 1, "lang": "en"}, "content.ingested:1")

    assert len(redis.queues["events"]) == 1
    envelope = json.loads(redis.queues["events"][0])
    assert envelope == {
        "topic": "content.ingested",
        "payload": {"content_id": 1, "lang": "en"},
        "idempotency_key": "content.ingested:1",
    }
    assert publisher.has_published("content.ingested:1")
