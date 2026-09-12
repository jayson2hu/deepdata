from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import feedparser
import httpx


@dataclass(frozen=True)
class RssEntry:
    title: str | None
    link: str
    published: str | None
    author: str | None
    summary: str | None
    raw: dict[str, Any]


def fetch_feed(
    feed_url: str,
    etag: str | None = None,
    modified: str | None = None,
) -> list[RssEntry]:
    parsed = urlparse(feed_url)
    if parsed.scheme == "file":
        data = _file_url_to_path(feed_url).read_bytes()
        parsed_feed = feedparser.parse(data)
    else:
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        response = httpx.get(feed_url, headers=headers, timeout=30, follow_redirects=True)
        if response.status_code == 304:
            return []
        response.raise_for_status()
        parsed_feed = feedparser.parse(response.content)
    if parsed_feed.bozo:
        raise ValueError(f"malformed feed: {parsed_feed.bozo_exception}")
    entries: list[RssEntry] = []
    for entry in parsed_feed.entries:
        raw = dict(entry)
        link = str(raw.get("link") or raw.get("id") or "")
        if not link:
            continue
        entries.append(
            RssEntry(
                title=raw.get("title"),
                link=link,
                published=raw.get("published"),
                author=raw.get("author"),
                summary=raw.get("summary"),
                raw=raw,
            )
        )
    return entries


def _file_url_to_path(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.endswith(":"):
        return Path(url2pathname(f"{parsed.netloc}{parsed.path}"))
    return Path(url2pathname(parsed.path))
