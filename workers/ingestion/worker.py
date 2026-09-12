from __future__ import annotations

from arq.connections import RedisSettings

from core_data.config import get_settings


async def ping(ctx: dict[str, object]) -> str:
    del ctx
    return "pong"


class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
