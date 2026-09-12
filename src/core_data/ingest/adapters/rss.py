from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from core_data.db.models import Source
from core_data.ingest.adapters.base import Entry
from core_data.ingest.rss import fetch_feed


@dataclass(frozen=True)
class RssAdapter:
    type: str = "rss"
    label: str = "RSS / Atom"
    needs_page_fetch: bool = True
    config_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "interval_min": {"type": "int", "default": 60},
            "render": {"type": "bool", "default": False},
        }
    )

    def fetch_entries(self, source: Source) -> Iterable[Entry]:
        if not source.feed_url:
            raise ValueError("source has no feed_url")
        for entry in fetch_feed(source.feed_url):
            yield Entry(
                url=entry.link,
                title=entry.title,
                raw=entry.raw,
                extra={"author": entry.author, "summary": entry.summary},
            )
