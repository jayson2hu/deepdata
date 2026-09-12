from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from core_data.config import get_settings
from core_data.db.bootstrap import create_all
from core_data.db.session import SessionLocal, engine
from core_data.events.outbox import relay_once
from core_data.ingest.pipeline import crawl_source
from core_data.ingest.scheduler import due_sources
from core_data.storage.factory import build_object_store
from core_data.storage.object_store import ObjectStore

HEARTBEAT_PATH = Path(".runtime") / "scheduler-heartbeat.json"


@dataclass(frozen=True)
class TickResult:
    last_tick: str
    due: int
    crawled: int
    failed: int
    relayed: int
    errors: list[str]


def _write_heartbeat(path: Path, result: TickResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")


def _log_publisher(topic: str, payload: dict[str, Any], key: str) -> None:
    print(f"[scheduler] relay {topic} {key} {payload}")


def run_tick(
    *,
    session_factory: sessionmaker[Any] = SessionLocal,
    object_store: ObjectStore | None = None,
    heartbeat_path: Path = HEARTBEAT_PATH,
    relay: bool = False,
) -> TickResult:
    store = object_store or build_object_store(get_settings())
    errors: list[str] = []
    crawled = 0
    failed = 0
    relayed = 0
    with session_factory() as session:
        sources = due_sources(session)
        due = len(sources)
        for source in sources:
            try:
                crawl_source(session, store, source)
                session.commit()
                crawled += 1
            except Exception as exc:
                session.rollback()
                failed += 1
                errors.append(f"source {source.id}: {exc}")
                print(f"[scheduler] source {source.id} failed: {exc}")
        if relay:
            relayed = relay_once(session, _log_publisher)
            session.commit()
    result = TickResult(
        last_tick=datetime.now(UTC).isoformat(timespec="seconds"),
        due=due,
        crawled=crawled,
        failed=failed,
        relayed=relayed,
        errors=errors,
    )
    _write_heartbeat(heartbeat_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick-sec", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--relay", action="store_true")
    args = parser.parse_args()

    create_all(engine)
    while True:
        result = run_tick(relay=args.relay)
        print(
            "[scheduler] tick "
            f"due={result.due} crawled={result.crawled} "
            f"failed={result.failed} relayed={result.relayed}"
        )
        if args.once:
            return
        time.sleep(max(1, args.tick_sec))


if __name__ == "__main__":
    main()
