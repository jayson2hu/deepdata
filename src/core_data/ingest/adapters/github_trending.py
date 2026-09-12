from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from lxml import html

from core_data.db.models import Source
from core_data.ingest.adapters.base import Entry

GITHUB_BASE = "https://github.com"
SINCE_VALUES = {"daily", "weekly", "monthly"}


def _int_from_text(value: str) -> int | None:
    match = re.search(r"[\d,]+", value)
    if match is None:
        return None
    return int(match.group(0).replace(",", ""))


def parse_trending(payload: bytes, *, language: str | None = None) -> list[Entry]:
    doc = html.fromstring(payload)
    entries: list[Entry] = []
    repos = doc.xpath("//article[contains(@class, 'Box-row')]")
    for rank, repo in enumerate(repos, start=1):
        link = repo.xpath(".//h2//a[1]")
        if not link:
            continue
        href = str(link[0].get("href") or "").strip()
        title = " ".join(link[0].text_content().split()).replace(" / ", "/")
        description_nodes = repo.xpath(".//p")
        description = (
            " ".join(description_nodes[0].text_content().split()) if description_nodes else None
        )
        stars_text = " ".join(repo.xpath(".//a[contains(@href, '/stargazers')]/text()"))
        stars_today_text = " ".join(
            repo.xpath(".//*[contains(., 'stars today') or contains(., 'star today')]/text()")
        )
        repo_language_nodes = repo.xpath(
            ".//*[contains(@itemprop, 'programmingLanguage')]/text()"
        )
        repo_language = (
            " ".join(repo_language_nodes[0].split()) if repo_language_nodes else language
        )
        url = f"{GITHUB_BASE}{href}" if href.startswith("/") else href
        extra = {
            "rank": rank,
            "stars": _int_from_text(stars_text),
            "stars_today": _int_from_text(stars_today_text),
            "language": repo_language,
            "description": description,
            "platform": "github",
        }
        entries.append(
            Entry(
                url=url,
                title=title,
                raw={"url": url, "title": title, **extra},
                extra={key: value for key, value in extra.items() if value is not None},
            )
        )
    return entries


@dataclass(frozen=True)
class GithubTrendingAdapter:
    type: str = "github_trending"
    label: str = "GitHub Trending"
    needs_page_fetch: bool = False
    config_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "language": {"type": "string", "default": ""},
            "since": {
                "type": "enum",
                "options": ["daily", "weekly", "monthly"],
                "default": "daily",
            },
            "interval_min": {"type": "int", "default": 180},
        }
    )

    def fetch_entries(self, source: Source) -> Iterable[Entry]:
        cfg = source.crawl_config or {}
        language = str(cfg.get("language") or "").strip()
        since = str(cfg.get("since") or "daily").strip().lower()
        if since not in SINCE_VALUES:
            raise ValueError("github_trending since must be daily, weekly, or monthly")
        path = f"/trending/{quote(language)}" if language else "/trending"
        response = httpx.get(
            f"{GITHUB_BASE}{path}",
            params={"since": since},
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "CodePick-L0/0.1"},
        )
        response.raise_for_status()
        return parse_trending(bytes(response.content), language=language or None)
