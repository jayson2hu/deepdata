from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from core_data.db.models import RawDocument
from core_data.ingest.fetcher import fetch_page
from core_data.ingest.pipeline import crawl_source
from core_data.ingest.rss import fetch_feed
from core_data.sources.repository import create_source


def test_fetch_feed_rejects_malformed_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<rss><channel><item>", encoding="utf-8")
    with pytest.raises(ValueError):
        fetch_feed(bad.as_uri())


def test_fetch_page_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fetch_page((tmp_path / "no-such-codepick-file.html").as_uri())


def test_pipeline_records_fetch_failure(session, object_store, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    missing = (tmp_path / "missing.html").as_uri()
    rss = tmp_path / "feed.xml"
    rss.write_text(
        f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>x</title>
<item><title>x</title><link>{missing}</link><guid>x</guid></item>
</channel></rss>""",
        encoding="utf-8",
    )
    source = create_source(session, name="Broken", feed_url=rss.as_uri())
    stats = crawl_source(session, object_store, source)

    assert stats["failed"] == 1
    assert session.scalar(select(func.count()).select_from(RawDocument)) == 2
    errors = [
        raw.extra.get("error")
        for raw in session.scalars(select(RawDocument).where(RawDocument.fetch_method == "error"))
    ]
    assert errors and "No such file" in errors[0]
