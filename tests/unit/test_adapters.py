from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from core_data.db.models import ContentItem, CrawlJob, RawDocument
from core_data.ingest import adapters
from core_data.ingest.adapters.base import Entry
from core_data.ingest.adapters.github_trending import parse_trending
from core_data.ingest.adapters.html_list import HtmlListConfig, parse_list
from core_data.ingest.adapters.platform_hot import NotImplementedHotAdapter, parse_hot_json
from core_data.ingest.canonical import TREND, build_content_item_from_entry
from core_data.ingest.pipeline import crawl_source
from core_data.ingest.raw_store import RawStore
from core_data.sources.repository import create_source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"
JSON_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "json"


def test_adapter_registry_lists_and_rejects_unknown_type() -> None:
    types = {item["type"] for item in adapters.list_types()}

    assert {
        "rss",
        "html_list",
        "github_trending",
        "baidu_hot",
        "zhihu_hot",
        "weibo_hot",
        "douyin_hot",
        "xiaohongshu",
    }.issubset(types)
    assert adapters.get_adapter("rss").needs_page_fetch is True
    with pytest.raises(ValueError, match="unknown source type"):
        adapters.get_adapter("missing")


def test_html_list_parse_css_and_xpath() -> None:
    payload = (FIXTURES / "html_list.html").read_bytes()

    css_entries = parse_list(
        payload,
        HtmlListConfig(
            list_url="https://news.example.test/",
            selector="article a.title",
            selector_type="css",
            base_url="https://news.example.test/",
            limit=2,
        ),
    )
    xpath_entries = parse_list(
        payload,
        HtmlListConfig(
            list_url="https://news.example.test/",
            selector="//article/a[@class='title']",
            selector_type="xpath",
            base_url="https://news.example.test/",
        ),
    )

    assert [entry.url for entry in css_entries] == [
        "https://news.example.test/alpha",
        "https://news.example.test/beta",
    ]
    assert [entry.title for entry in xpath_entries] == [
        "Alpha story",
        "Beta story",
        "Gamma story",
    ]


def test_github_trending_parse_fixture() -> None:
    entries = parse_trending((FIXTURES / "github_trending.html").read_bytes(), language="python")

    assert len(entries) == 2
    assert entries[0].url == "https://github.com/owner-one/repo-one"
    assert entries[0].title == "owner-one/repo-one"
    assert entries[0].extra["rank"] == 1
    assert entries[0].extra["stars"] == 1234
    assert entries[0].extra["stars_today"] == 45
    assert entries[0].extra["platform"] == "github"


def test_platform_hot_json_parse_fixture() -> None:
    payload = json.loads((JSON_FIXTURES / "hot_list.json").read_text(encoding="utf-8"))

    entries = parse_hot_json(payload, platform="baidu_hot")

    assert len(entries) == 2
    assert entries[0].title == "Alpha hot topic"
    assert entries[0].extra == {"rank": 1, "heat": "999", "platform": "baidu_hot", "tags": []}
    assert entries[1].url == "https://example.test/b"


def test_not_implemented_platform_adapter_reports_clear_error() -> None:
    adapter = NotImplementedHotAdapter("douyin_hot", "Douyin Hot")
    with pytest.raises(NotImplementedError, match="authorized API/cookie"):
        list(adapter.fetch_entries(None))  # type: ignore[arg-type]


def test_build_content_item_from_entry_creates_trend_and_dedups(session, object_store) -> None:  # type: ignore[no-untyped-def]
    source = create_source(session, name="Trending", feed_url=None, source_type="github_trending")
    raw_store = RawStore(session, object_store)
    raw = raw_store.append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://github.com/owner/repo",
        fetch_method="github_trending",
        raw_entry={"rank": 1},
    )
    entry = Entry(
        url="https://github.com/owner/repo",
        title="owner/repo",
        raw={"rank": 1},
        extra={"rank": 1, "stars": 100, "platform": "github"},
    )

    item = build_content_item_from_entry(session, raw, entry)
    duplicate_raw = raw_store.append(
        source_id=source.id,
        crawl_job_id=None,
        url="https://github.com/owner/repo?utm_source=x",
        fetch_method="github_trending",
        raw_entry={"rank": 2},
    )
    same_item = build_content_item_from_entry(
        session,
        duplicate_raw,
        Entry(url="https://github.com/owner/repo?utm_source=x", title="owner/repo"),
    )

    assert item.status == TREND
    assert item.meta["rank"] == 1
    assert same_item.id == item.id
    assert session.scalar(select(func.count()).select_from(ContentItem)) == 1


def test_pipeline_crawls_github_trending_without_page_fetch(
    session,
    object_store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    class FixtureAdapter:
        type = "github_trending"
        label = "GitHub Trending"
        needs_page_fetch = False
        config_schema = {}

        def fetch_entries(self, source):  # type: ignore[no-untyped-def]
            return [
                Entry(
                    url="https://github.com/owner/repo",
                    title="owner/repo",
                    raw={"rank": 1},
                    extra={"rank": 1, "stars": 100, "platform": "github"},
                )
            ]

    monkeypatch.setattr("core_data.ingest.pipeline.get_adapter", lambda type_: FixtureAdapter())
    source = create_source(session, name="Trending", feed_url=None, source_type="github_trending")

    stats = crawl_source(session, object_store, source)

    assert stats == {
        "entries": 1, "raw": 1, "content": 1, "failed": 0, "rejected": 0,
        "media": 0, "trend": 1,
    }
    assert session.scalar(select(func.count()).select_from(RawDocument)) == 1
    assert session.scalar(select(func.count()).select_from(ContentItem)) == 1
    job = session.scalar(select(CrawlJob))
    assert job is not None
    assert job.kind == "github_trending"
