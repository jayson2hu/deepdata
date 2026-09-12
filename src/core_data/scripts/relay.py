from __future__ import annotations

import argparse
from typing import cast

from redis import Redis

from core_data.config import get_settings
from core_data.db.session import SessionLocal
from core_data.events.outbox import relay_once
from core_data.events.publishers import RedisLike, RedisStreamPublisher


def relay_once_to_redis() -> int:
    settings = get_settings()
    redis_client = cast(RedisLike, Redis.from_url(settings.redis_url, decode_responses=True))
    publisher = RedisStreamPublisher(redis_client)
    with SessionLocal() as session:
        count = relay_once(session, publisher)
        session.commit()
        return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="relay one batch and exit")
    args = parser.parse_args()
    if not args.once:
        raise SystemExit("only --once is currently supported")
    count = relay_once_to_redis()
    print(f"L0 RELAY: published={count}")


if __name__ == "__main__":
    main()
