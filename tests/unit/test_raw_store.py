from __future__ import annotations

from core_data.ingest.raw_store import RawStore
from core_data.sources.repository import create_source


def test_raw_store_is_append_only(session, object_store) -> None:  # type: ignore[no-untyped-def]
    assert not hasattr(RawStore, "update")
    assert not hasattr(RawStore, "delete")

    source = create_source(session, name="Fixture", feed_url="https://example.com/rss.xml")
    store = RawStore(session, object_store)
    first = store.append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://example.com/a",
        fetch_method="httpx",
        raw_html=b"<html>one</html>",
    )
    second = store.append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://example.com/a",
        fetch_method="httpx",
        raw_html=b"<html>two</html>",
    )
    assert first.id != second.id
    assert first.raw_html_ref is not None
    assert object_store.exists(first.raw_html_ref)
