from __future__ import annotations

from sqlalchemy import func, select

from core_data.db.models import ContentItem, OutboxEvent, RawDocument
from core_data.events.outbox import relay_once
from core_data.ingest.pipeline import crawl_source
from core_data.query.api import get_content, list_contents
from core_data.sources.repository import create_source


def test_pipeline_preserves_raw_builds_content_and_emits_contract_event(
    session, object_store, fixture_rss  # type: ignore[no-untyped-def]
) -> None:
    source = create_source(session, name="Fixture", feed_url=fixture_rss.as_uri())
    stats = crawl_source(session, object_store, source)

    assert stats["entries"] == 1
    assert session.scalar(select(func.count()).select_from(RawDocument)) == 2
    assert session.scalar(select(func.count()).select_from(ContentItem)) == 1

    page = list_contents(session, status="WAIT_FILTER", since=None, limit=1, cursor=None)
    assert len(page.items) == 1
    content = get_content(session, object_store, page.items[0].id)
    event = session.scalar(select(OutboxEvent))
    assert event is not None
    assert event.topic == "content.ingested"
    assert event.payload == {
        "schema_version": 1,
        "content_id": content.id,
        "content_version": 1,
        "content_hash": session.get(ContentItem, content.id).content_hash,
        "lang": content.lang,
    }

    assert content.status == "WAIT_FILTER"
    assert "immutable raw data layer" in content.clean_text

    published: list[str] = []
    assert relay_once(session, lambda topic, payload, key: published.append(key)) == 1
    assert published == [f"content.ingested:{content.id}:v1"]
