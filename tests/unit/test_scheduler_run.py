from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from core_data.db.models import ContentItem, RawDocument
from core_data.ingest.adapters.base import Entry
from core_data.scripts.scheduler_run import run_tick
from core_data.sources.repository import create_source


def test_run_tick_crawls_due_sources_and_writes_heartbeat(
    session,
    object_store,
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    source = create_source(session, name="Trending", feed_url=None, source_type="github_trending")
    session.commit()
    maker = sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )

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
                    extra={"rank": 1, "platform": "github"},
                )
            ]

    monkeypatch.setattr("core_data.ingest.pipeline.get_adapter", lambda type_: FixtureAdapter())
    heartbeat = tmp_path / "heartbeat.json"

    result = run_tick(
        session_factory=maker,
        object_store=object_store,
        heartbeat_path=heartbeat,
    )

    assert result.due == 1
    assert result.crawled == 1
    assert result.failed == 0
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["due"] == 1
    with maker() as verify:
        assert verify.scalar(select(func.count()).select_from(RawDocument)) == 1
        assert verify.scalar(select(func.count()).select_from(ContentItem)) == 1
        assert verify.get(type(source), source.id) is not None
