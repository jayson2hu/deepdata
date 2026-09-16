from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from core_data.db.models import ContentItem, ContentVersion, OutboxEvent
from core_data.ingest.canonical import build_content_item
from core_data.ingest.extractor import extract
from core_data.ingest.raw_store import RawStore
from core_data.sources.repository import create_source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"


def test_same_url_changed_content_creates_new_version(session, object_store) -> None:  # type: ignore[no-untyped-def]
    source = create_source(session, name="Fixture", feed_url="https://example.com/rss.xml")
    raw_store = RawStore(session, object_store)
    html1 = (FIXTURES / "article1.html").read_bytes()
    html2 = (FIXTURES / "article1_updated.html").read_bytes()

    raw1 = raw_store.append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://example.com/a",
        fetch_method="httpx",
        raw_html=html1,
    )
    item = build_content_item(session, object_store, raw1, extract(html1, raw1.url))
    raw2 = raw_store.append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://example.com/a?utm_source=x",
        fetch_method="httpx",
        raw_html=html2,
    )
    updated = build_content_item(session, object_store, raw2, extract(html2, raw2.url))

    assert updated.id == item.id
    assert updated.current_version == 2
    assert session.scalar(select(func.count()).select_from(ContentVersion)) == 2
    assert session.scalar(select(func.count()).select_from(ContentItem)) == 1
    events = session.scalars(select(OutboxEvent).order_by(OutboxEvent.id)).all()
    assert [event.idempotency_key for event in events] == [
        f"content.ingested:{item.id}:v1",
        f"content.ingested:{item.id}:v2",
    ]
    assert [event.payload["content_version"] for event in events] == [1, 2]
    assert events[-1].payload["content_hash"] == updated.content_hash
