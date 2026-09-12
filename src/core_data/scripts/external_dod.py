from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any, cast

from redis import Redis
from sqlalchemy import text

from core_data.config import get_settings
from core_data.db.session import SessionLocal, engine
from core_data.events.outbox import emit, relay_once
from core_data.events.publishers import RedisLike, RedisStreamPublisher
from core_data.scripts.integration_smoke import main as integration_smoke_main
from core_data.scripts.soak import run_soak


def main(argv: list[str] | None = None) -> None:
    os.chdir(Path(__file__).resolve().parents[3])
    parser = argparse.ArgumentParser()
    parser.add_argument("--soak-hours", type=float, default=24.0)
    parser.add_argument("--interval-sec", type=float, default=300.0)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(".runtime/external-dod-soak-report.json"),
    )
    parser.add_argument("--skip-soak", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        raise SystemExit("DATABASE_URL must point at PostgreSQL for external DoD")
    if settings.object_store_backend.lower() != "s3":
        raise SystemExit("OBJECT_STORE_BACKEND must be s3 for external DoD")

    _run_external_smoke()
    relay_summary = _verify_redis_relay()

    soak_summary: dict[str, Any] | None = None
    if not args.skip_soak:
        run_soak(
            hours=args.soak_hours,
            interval_sec=args.interval_sec,
            report_path=args.report,
            seed_fixture=True,
            min_new_raw=1,
            min_new_content=1,
        )
        soak_summary = json.loads(args.report.read_text(encoding="utf-8"))

    print(
        json.dumps(
            {
                "external_dod": True,
                "database_url": _redact_url(settings.database_url),
                "redis_url": _redact_url(settings.redis_url),
                "object_store_backend": settings.object_store_backend,
                "s3_endpoint": settings.s3_endpoint,
                "s3_bucket": settings.s3_bucket,
                "relay": relay_summary,
                "soak": soak_summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _run_external_smoke() -> None:
    import sys

    previous_argv = sys.argv
    sys.argv = ["integration_smoke", "--require-external"]
    try:
        integration_smoke_main()
    finally:
        sys.argv = previous_argv


def _verify_redis_relay() -> dict[str, Any]:
    settings = get_settings()
    redis_client = cast(Any, Redis.from_url(settings.redis_url, decode_responses=True))
    redis_client.ping()
    publisher = RedisStreamPublisher(cast(RedisLike, redis_client))

    probe_id = uuid.uuid4().hex
    idempotency_key = f"content.ingested:external-dod:{probe_id}"
    topic = "content.ingested"
    payload = {"content_id": -1, "lang": "en"}

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    with SessionLocal() as session:
        assert emit(session, topic, payload, idempotency_key)
        session.commit()

    before = int(redis_client.llen(publisher.queue_name))
    with SessionLocal() as session:
        first_count = relay_once(session, publisher)
        session.commit()
    after_first = int(redis_client.llen(publisher.queue_name))

    publisher(topic, payload, idempotency_key)
    after_duplicate_publish = int(redis_client.llen(publisher.queue_name))

    with SessionLocal() as session:
        second_count = relay_once(session, publisher)
        session.commit()
    after_second = int(redis_client.llen(publisher.queue_name))

    entries = redis_client.lrange(publisher.queue_name, max(after_first - 3, 0), after_first - 1)
    matching = [json.loads(entry) for entry in entries if idempotency_key in entry]
    if first_count != 1:
        raise SystemExit(f"expected first relay to publish 1 event, got {first_count}")
    if second_count != 0:
        raise SystemExit(f"expected second relay to publish 0 events, got {second_count}")
    if after_first != before + 1:
        raise SystemExit("Redis queue did not receive exactly one relay envelope")
    if after_duplicate_publish != after_first or after_second != after_first:
        raise SystemExit("Redis idempotency check allowed a duplicate envelope")
    if len(matching) != 1:
        raise SystemExit("Redis queue does not contain exactly one matching relay envelope")
    envelope = matching[0]
    if envelope != {"topic": topic, "payload": payload, "idempotency_key": idempotency_key}:
        raise SystemExit(f"unexpected relay envelope: {envelope}")

    return {
        "idempotency_key": idempotency_key,
        "first_relay_count": first_count,
        "second_relay_count": second_count,
        "queue_before": before,
        "queue_after": after_first,
        "duplicate_publish_queue_after": after_duplicate_publish,
    }


def _redact_url(value: str) -> str:
    if "@" not in value:
        return value
    scheme, rest = value.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


if __name__ == "__main__":
    main()
