from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.models import Source, SourceHealth


def create_source(
    session: Session,
    *,
    name: str,
    feed_url: str | None,
    home_url: str | None = None,
    source_type: str = "article",
    crawl_config: dict[str, object] | None = None,
) -> Source:
    if feed_url is not None:
        existing = session.scalar(select(Source).where(Source.feed_url == feed_url))
        if existing is not None:
            raise ValueError(f"duplicate feed_url: {feed_url}")
    source = Source(
        name=name,
        feed_url=feed_url,
        home_url=home_url,
        type=source_type,
        crawl_config=crawl_config or {},
    )
    session.add(source)
    session.flush()
    session.add(SourceHealth(source_id=source.id, status="unknown"))
    session.flush()
    return source


def list_enabled_sources(session: Session) -> list[Source]:
    return list(session.scalars(select(Source).where(Source.enabled.is_(True))).all())
