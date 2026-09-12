from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from core_data.db.models import SourceHealth
from core_data.ingest.media import fetch_and_store_media, media_refs_from_entry
from core_data.ingest.pipeline import crawl_source
from core_data.ingest.scheduler import due_sources
from core_data.sources.repository import create_source


def test_media_assets_are_stored_and_referenced(object_store, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    image = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\nfixture")

    asset = fetch_and_store_media(object_store, source_id=7, url=image.as_uri())
    assert asset.size == len(b"\x89PNG\r\nfixture")
    assert asset.content_type == "image/png"
    assert object_store.exists(asset.ref)

    refs = media_refs_from_entry(
        object_store,
        source_id=7,
        raw_entry={"media_content": [{"url": image.as_uri()}]},
    )
    assert refs[0]["url"] == image.as_uri()
    assert object_store.exists(str(refs[0]["ref"]))


def test_pipeline_updates_source_health(session, object_store, fixture_rss) -> None:  # type: ignore[no-untyped-def]
    source = create_source(session, name="Fixture", feed_url=fixture_rss.as_uri())
    stats = crawl_source(session, object_store, source)

    health = session.get(SourceHealth, source.id)
    assert stats["failed"] == 0
    assert health is not None
    assert health.status == "ok"
    assert health.fail_count == 0
    assert health.last_ok_at is not None


def test_due_sources_respects_interval(session) -> None:  # type: ignore[no-untyped-def]
    source = create_source(
        session,
        name="Due",
        feed_url="https://example.com/due.xml",
        crawl_config={"interval_min": 30},
    )
    health = session.get(SourceHealth, source.id)
    assert health is not None
    health.last_attempt_at = datetime.now(UTC) - timedelta(minutes=31)

    assert [s.id for s in due_sources(session)] == [source.id]

    health.last_attempt_at = datetime.now(UTC) - timedelta(minutes=10)
    assert due_sources(session) == []
