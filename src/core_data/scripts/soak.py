from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core_data.config import get_settings
from core_data.db.bootstrap import create_all
from core_data.db.models import ContentItem, OutboxEvent, RawDocument, Source, SourceHealth
from core_data.db.session import SessionLocal, engine
from core_data.events.outbox import relay_once
from core_data.ingest.pipeline import crawl_source
from core_data.ingest.scheduler import due_sources
from core_data.sources.repository import create_source
from core_data.storage.factory import build_object_store


def run_soak(
    *,
    hours: float,
    interval_sec: float,
    report_path: Path,
    seed_fixture: bool,
    min_new_raw: int,
    min_new_content: int,
) -> None:
    settings = get_settings()
    create_all(engine)
    store = build_object_store(settings)
    deadline = time.monotonic() + hours * 3600
    iterations = 0
    delivered = 0
    errors: list[str] = []

    with SessionLocal() as session:
        if seed_fixture:
            _ensure_fixture_source(session)
            session.commit()
        initial_raw = session.scalar(select(func.count()).select_from(RawDocument)) or 0
        initial_content = session.scalar(select(func.count()).select_from(ContentItem)) or 0

    while time.monotonic() < deadline or iterations == 0:
        iterations += 1
        with SessionLocal() as session:
            try:
                for source in due_sources(session):
                    crawl_source(session, store, source, fetch_media=True)
                delivered += relay_once(session, lambda topic, payload, key: None)
                session.commit()
            except Exception as exc:  # keep soak running while recording failures
                session.rollback()
                errors.append(str(exc))

        if time.monotonic() < deadline:
            time.sleep(interval_sec)

    with SessionLocal() as session:
        final_raw = session.scalar(select(func.count()).select_from(RawDocument)) or 0
        final_content = session.scalar(select(func.count()).select_from(ContentItem)) or 0
        new_raw = final_raw - initial_raw
        new_content = final_content - initial_content
        summary = {
            "started_at": datetime.now(UTC).isoformat(),
            "hours_requested": hours,
            "iterations": iterations,
            "initial_raw_documents": initial_raw,
            "initial_content_items": initial_content,
            "raw_documents": final_raw,
            "content_items": final_content,
            "new_raw_documents": new_raw,
            "new_content_items": new_content,
            "min_new_raw": min_new_raw,
            "min_new_content": min_new_content,
            "outbox_events": session.scalar(select(func.count()).select_from(OutboxEvent)) or 0,
            "events_relayed": delivered,
            "errors": errors,
        }
        summary["pass"] = (
            not errors and new_raw >= min_new_raw and new_content >= min_new_content
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if not summary["pass"]:
        raise SystemExit(1)
    print(f"L0 SOAK: PASS iterations={iterations} report={report_path}")


def _ensure_fixture_source(session: Session) -> Source:
    repo_root = Path(__file__).resolve().parents[3]
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    runtime_dir = repo_root / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_html = runtime_dir / f"soak-{stamp}.html"
    runtime_html.write_text(
        f"""<!doctype html>
<html>
  <head><title>Soak Fixture {stamp}</title></head>
  <body><main>Unique soak content {stamp} proves unattended ingestion progress.</main></body>
</html>
""",
        encoding="utf-8",
    )
    rss_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CodePick Soak Fixture</title>
    <link>https://example.com</link>
    <description>Generated soak feed</description>
    <item>
      <title>Soak Fixture {stamp}</title>
      <link>{runtime_html.resolve().as_uri()}</link>
      <guid>soak-{stamp}</guid>
      <description>Generated soak item</description>
    </item>
  </channel>
</rss>
"""
    runtime_rss = repo_root / ".runtime" / "soak.xml"
    runtime_rss.write_text(rss_text, encoding="utf-8")
    feed_url = runtime_rss.as_uri()
    existing = session.scalar(select(Source).where(Source.feed_url == feed_url))
    if existing is not None:
        existing.crawl_config = {"interval_min": 0}
        health = session.get(SourceHealth, existing.id)
        if health is not None:
            health.last_attempt_at = None
        return existing
    return create_source(
        session,
        name="Soak Fixture",
        feed_url=feed_url,
        crawl_config={"interval_min": 0},
    )


def main() -> None:
    os.chdir(Path(__file__).resolve().parents[3])
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--interval-sec", type=float, default=300.0)
    parser.add_argument("--report", type=Path, default=Path(".runtime/soak-report.json"))
    parser.add_argument("--seed-fixture", action="store_true")
    parser.add_argument("--min-new-raw", type=int, default=1)
    parser.add_argument("--min-new-content", type=int, default=1)
    args = parser.parse_args()
    run_soak(
        hours=args.hours,
        interval_sec=args.interval_sec,
        report_path=args.report,
        seed_fixture=args.seed_fixture,
        min_new_raw=args.min_new_raw,
        min_new_content=args.min_new_content,
    )


if __name__ == "__main__":
    main()
