from __future__ import annotations

import json
from typing import Any, Protocol

# Redis runs the script without another client interleaving commands. Lua errors do not
# roll back earlier commands, so enqueue BEFORE recording acceptance: a failed RPUSH
# must never leave a marker that makes a later relay silently discard the event.
_PUBLISH_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
redis.call('RPUSH', KEYS[2], ARGV[1])
redis.call('SET', KEYS[1], '1', 'EX', ARGV[2])
return 1
"""


class RedisLike(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> object: ...

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
        if (
            isinstance(ttl_sec, bool)
            or not isinstance(ttl_sec, int)
            or not 1 <= ttl_sec <= 2**31 - 1
        ):
            raise ValueError("ttl_sec must be an integer between 1 and 2147483647")
        self.redis = redis_client
        self.queue_name = queue_name
        self.key_prefix = key_prefix
        self.ttl_sec = ttl_sec

    def __call__(self, topic: str, payload: dict[str, Any], idempotency_key: str) -> None:
        accepted_key = self._key(idempotency_key)
        if accepted_key == self.queue_name:
            raise ValueError("queue and acceptance marker must use different Redis keys")
        envelope = {
            "topic": topic,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        # Validate JSON before Redis writes anything, leaving invalid events retryable.
        serialized = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
        self.redis.eval(
            _PUBLISH_LUA, 2, accepted_key, self.queue_name, serialized, self.ttl_sec,
        )

    def already_published(self) -> set[str]:
        return set()

    def has_published(self, idempotency_key: str) -> bool:
        return bool(self.redis.exists(self._key(idempotency_key)))

    def _key(self, idempotency_key: str) -> str:
        return f"{self.key_prefix}:{idempotency_key}"
