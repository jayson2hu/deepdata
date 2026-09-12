from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from core_data.db.models import ContentItem, Source
from core_data.query.contracts import ContentOut, ContentRef, Page, SourceRef
from core_data.storage.object_store import ObjectStore


def _source_ref(session: Session, source_id: int | None) -> SourceRef:
    source = session.get(Source, source_id) if source_id is not None else None
    return SourceRef(id=source.id if source else source_id, name=source.name if source else None)


def _ref(session: Session, item: ContentItem) -> ContentRef:
    return ContentRef(
        id=item.id,
        canonical_url=item.canonical_url,
        title=item.title,
        lang=item.lang,
        source=_source_ref(session, item.source_id),
        published_at=item.published_at,
        status=item.status,
    )


def list_contents(
    session: Session,
    *,
    status: str | None,
    since: datetime | None,
    limit: int,
    cursor: str | None,
) -> Page[ContentRef]:
    if limit <= 0 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    conditions = []
    if status:
        conditions.append(ContentItem.status == status)
    if since:
        conditions.append(ContentItem.fetched_at >= since)
    if cursor:
        conditions.append(ContentItem.id > int(cursor))
    stmt = select(ContentItem)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    rows = session.scalars(stmt.order_by(ContentItem.id).limit(limit + 1)).all()
    page_rows = rows[:limit]
    next_cursor = str(page_rows[-1].id) if len(rows) > limit and page_rows else None
    return Page(items=[_ref(session, row) for row in page_rows], next_cursor=next_cursor)


def get_content(session: Session, object_store: ObjectStore, content_id: int) -> ContentOut:
    item = session.get(ContentItem, content_id)
    if item is None:
        raise LookupError(content_id)
    clean_text = ""
    if item.clean_text_ref:
        clean_text = object_store.get_bytes(item.clean_text_ref).decode("utf-8")
    ref = _ref(session, item)
    return ContentOut(**ref.model_dump(), clean_text=clean_text)
