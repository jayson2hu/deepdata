from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from core_data.config import get_settings
from core_data.db.bootstrap import create_all
from core_data.db.models import ContentItem, OutboxEvent, RawDocument, Source
from core_data.db.session import SessionLocal, engine
from core_data.events.outbox import relay_once
from core_data.ingest.pipeline import crawl_source
from core_data.query.api import get_content, list_contents
from core_data.sources.repository import create_source
from core_data.storage.factory import build_object_store


def smoke() -> None:
    settings = get_settings()
    if settings.database_url.startswith("sqlite:///"):
        engine.dispose()
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            db_path.unlink()
    if settings.object_store_root.exists():
        shutil.rmtree(settings.object_store_root)
    create_all(engine)
    store = build_object_store(settings)

    published: list[str] = []
    with SessionLocal() as session:
        repo_root = Path(__file__).resolve().parents[3]
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        runtime_html = repo_root / ".runtime" / f"smoke-{stamp}.html"
        runtime_html.parent.mkdir(parents=True, exist_ok=True)
        runtime_html.write_text(
            f"""<!doctype html>
<html>
  <head><title>Smoke Fixture {stamp}</title></head>
  <body>
    <main>Unique smoke content {stamp} proves the immutable raw data layer.</main>
  </body>
</html>
""",
            encoding="utf-8",
        )
        rss_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CodePick Smoke Fixture</title>
    <link>https://example.com</link>
    <description>Generated smoke feed</description>
    <item>
      <title>Smoke Fixture {stamp}</title>
      <link>{runtime_html.resolve().as_uri()}</link>
      <guid>smoke-{stamp}</guid>
      <description>Generated smoke item</description>
    </item>
  </channel>
</rss>
"""
        runtime_rss = repo_root / ".runtime" / f"smoke-{stamp}.xml"
        runtime_rss.write_text(rss_text, encoding="utf-8")
        fixture = runtime_rss.as_uri()
        source = session.scalar(select(Source).where(Source.feed_url == fixture))
        if source is None:
            source = create_source(session, name="Smoke Fixture", feed_url=fixture)
        else:
            source.crawl_config = {"interval_min": 0}
            if source.health is not None:
                source.health.last_attempt_at = None
        session.commit()

        stats = crawl_source(session, store, source)
        raw_count = session.scalar(select(func.count()).select_from(RawDocument)) or 0
        content_count = session.scalar(select(func.count()).select_from(ContentItem)) or 0
        outbox_count = session.scalar(select(func.count()).select_from(OutboxEvent)) or 0
        pending_outbox_count = (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
            )
            or 0
        )
        assert raw_count > 0, "raw_documents empty"
        assert content_count > 0, "content_items empty"
        assert outbox_count > 0, "outbox empty"
        assert pending_outbox_count > 0, "unpublished outbox empty"

        page = list_contents(session, status="WAIT_FILTER", since=None, limit=10, cursor=None)
        assert page.items, "list_contents returned no items"
        content = get_content(session, store, page.items[0].id)
        assert content.clean_text, "clean_text empty"

        item = session.get(ContentItem, page.items[0].id)
        assert item is not None and item.raw_document_id is not None
        raw = session.get(RawDocument, item.raw_document_id)
        assert raw is not None and raw.raw_html_ref and store.exists(raw.raw_html_ref)

        relayed = relay_once(session, lambda topic, payload, key: published.append(key))
        session.commit()
        assert relayed == pending_outbox_count
        assert len(set(published)) == relayed

        source_count = session.scalar(select(func.count()).select_from(Source)) or 0
        print(
            "L0 PIPELINE: PASS "
            f"sources={source_count} entries={stats['entries']} raw={raw_count} "
            f"content={content_count} events={relayed} failed={stats['failed']}"
        )


if __name__ == "__main__":
    smoke()
