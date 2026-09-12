from __future__ import annotations

from pathlib import Path

import pytest

from core_data.sources.opml import import_opml
from core_data.sources.repository import create_source, list_enabled_sources


def test_create_source_rejects_duplicate_feed_url(session) -> None:  # type: ignore[no-untyped-def]
    create_source(session, name="One", feed_url="https://example.com/feed.xml")
    with pytest.raises(ValueError):
        create_source(session, name="Two", feed_url="https://example.com/feed.xml")


def test_import_opml_is_idempotent(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    opml = tmp_path / "feeds.opml"
    opml.write_text(
        """<?xml version="1.0"?>
<opml version="2.0"><body>
  <outline text="A" title="A" type="rss" xmlUrl="https://example.com/a.xml" htmlUrl="https://example.com"/>
  <outline text="No feed"/>
</body></opml>""",
        encoding="utf-8",
    )

    assert import_opml(session, opml) == 1
    assert import_opml(session, opml) == 0
    sources = list_enabled_sources(session)
    assert len(sources) == 1
    assert sources[0].name == "A"
