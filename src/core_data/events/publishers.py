from __future__ import annotations

import json
from typing import Any, Protocol


class RedisLike(Protocol):
    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None) -> object: ...

    def rpush(self, name: str, value: str) -> object: ...

    def exists(self, name: str) -> int: ...


class RedisStreamPublisher:
    def __init__(
        self,
        redis_client: RedisLike,
        *,
        queue_name: str = "codepick:l0:events",
        key_prefix: str = "codepick:l0:published",
        ttl_sec: int = 7 * 24 * 3600,
    ) -> None:
        self.redis = redis_client
        self.queue_name = queue_name
        self.key_prefix = key_prefix
        self.ttl_sec = ttl_sec

    def __call__(self, topic: str, payload: dict[str, Any], idempotency_key: str) -> None:
        accepted_key = self._key(idempotency_key)
        accepted = self.redis.set(accepted_key, "1", nx=True, ex=self.ttl_sec)
        if not accepted:
            return
        envelope = {
            "topic": topic,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        self.redis.rpush(self.queue_name, json.dumps(envelope, ensure_ascii=False, sort_keys=True))

    def already_published(self) -> set[str]:
        return set()

    def has_published(self, idempotency_key: str) -> bool:
        return bool(self.redis.exists(self._key(idempotency_key)))

    def _key(self, idempotency_key: str) -> str:
        return f"{self.key_prefix}:{idempotency_key}"
