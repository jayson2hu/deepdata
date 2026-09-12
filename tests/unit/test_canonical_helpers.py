from __future__ import annotations

from pathlib import Path

import pytest

from core_data.ingest.canonical import build_content_item, lineage, rebuild_canonical
from core_data.ingest.extractor import extract
from core_data.ingest.raw_store import RawStore
from core_data.sources.repository import create_source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"


def test_lineage_and_rebuild_from_raw(session, object_store) -> None:  # type: ignore[no-untyped-def]
    source = create_source(session, name="Fixture", feed_url="https://example.com/rss.xml")
    html = (FIXTURES / "article1.html").read_bytes()
    raw = RawStore(session, object_store).append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://example.com/a",
        fetch_method="httpx",
        raw_html=html,
    )
    item = build_content_item(session, object_store, raw, extract(html, raw.url))

    assert lineage(session, item.id) == {
        "content_id": item.id,
        "raw_document_id": raw.id,
        "crawl_job_id": None,
        "source_id": source.id,
    }

    item.title = "stale"
    rebuilt = rebuild_canonical(session, object_store, item.id)
    assert rebuilt.title == "Code agents need durable raw data"


def test_rebuild_unknown_content_raises(session, object_store) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LookupError):
        rebuild_canonical(session, object_store, 404)
