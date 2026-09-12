from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core_data.db.models import Base
from core_data.storage.object_store import FileObjectStore


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with maker() as db:
        yield db


@pytest.fixture()
def object_store(tmp_path: Path) -> FileObjectStore:
    return FileObjectStore(tmp_path / "objects")


@pytest.fixture()
def fixture_rss(tmp_path: Path) -> Path:
    html_dir = (Path(__file__).parent / "fixtures" / "html").resolve()
    rss = (Path(__file__).parent / "fixtures" / "rss" / "normal.xml").read_text(encoding="utf-8")
    rss = rss.replace("file://PLACEHOLDER", html_dir.as_uri())
    target = tmp_path / "normal.xml"
    target.write_text(rss, encoding="utf-8")
    return target
