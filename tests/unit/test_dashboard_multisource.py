from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core_data.db.models import Base, Source
from core_data.scripts import dashboard
from core_data.storage.object_store import FileObjectStore


@pytest.fixture()
def dashboard_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[sessionmaker[Any]]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(dashboard, "SessionLocal", maker)
    monkeypatch.setattr(dashboard, "build_object_store", lambda settings: FileObjectStore(tmp_path))
    monkeypatch.setattr(dashboard, "get_settings", lambda: SimpleNamespace())
    yield maker


def test_create_source_accepts_type_and_crawl_config(dashboard_db: sessionmaker[Any]) -> None:
    payload = dashboard._create_source(
        {
            "name": "GitHub Trending",
            "type": "github_trending",
            "crawl_config": {"language": "python", "since": "daily", "interval_min": 180},
        }
    )

    assert payload["type"] == "github_trending"
    with dashboard_db() as session:
        source = session.scalar(select(Source))
        assert source is not None
        assert source.type == "github_trending"
        assert source.crawl_config["interval_min"] == 180


def test_create_source_rejects_unknown_type_and_invalid_config(
    dashboard_db: sessionmaker[Any],
) -> None:
    with pytest.raises(ValueError, match="unknown source type"):
        dashboard._create_source({"name": "Bad", "type": "missing"})
    with pytest.raises(ValueError, match="crawl_config must be an object"):
        dashboard._create_source({"name": "Bad", "crawl_config": "not-json"})


def test_status_includes_multisource_fields(
    dashboard_db: sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard._create_source(
        {
            "name": "GitHub Trending",
            "type": "github_trending",
            "crawl_config": {"interval_min": 180},
        }
    )
    monkeypatch.setattr(
        dashboard,
        "_scheduler_status",
        lambda: {"running": True, "last_tick": "2026-06-04T00:00:00+00:00"},
    )

    payload = dashboard._status()

    assert payload["scheduler"]["running"] is True
    assert payload["sources"][0]["type"] == "github_trending"
    assert payload["sources"][0]["interval_min"] == 180
    assert "next_run" in payload["sources"][0]
