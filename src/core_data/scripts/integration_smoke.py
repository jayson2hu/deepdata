from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, cast

os.chdir(Path(__file__).resolve().parents[3])

from redis import Redis  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from core_data.config import get_settings  # noqa: E402
from core_data.scripts.smoke import smoke  # noqa: E402
from core_data.storage.factory import build_object_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-external", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if args.require_external:
        _assert_external_database(settings.database_url)
        _assert_external_redis(settings.redis_url)
        _assert_external_object_store()

    smoke()


def _assert_external_database(database_url: str) -> None:
    if database_url.startswith("sqlite"):
        raise SystemExit("DATABASE_URL must point at PostgreSQL for external smoke")
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _assert_external_redis(redis_url: str) -> None:
    client = cast(Any, Redis.from_url(redis_url, decode_responses=True))
    if not client.ping():
        raise SystemExit("redis health check failed")


def _assert_external_object_store() -> None:
    settings = get_settings()
    store = build_object_store(settings)
    key = "health/integration-smoke.txt"
    store.put_bytes(key, b"ok", "text/plain")
    if not store.exists(key):
        raise SystemExit("object store health check failed")
    if store.get_bytes(key) != b"ok":
        raise SystemExit("object store round trip failed")


if __name__ == "__main__":
    main()
