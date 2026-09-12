from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select

from core_data.config import get_settings
from core_data.db.bootstrap import create_all
from core_data.db.models import (
    ContentItem,
    ContentVersion,
    CrawlJob,
    OutboxEvent,
    RawDocument,
    Source,
)
from core_data.db.session import SessionLocal, engine
from core_data.ingest.adapters import get_adapter, list_types
from core_data.ingest.pipeline import crawl_source
from core_data.scripts.scheduler_run import HEARTBEAT_PATH
from core_data.sources.repository import create_source
from core_data.storage.factory import build_object_store

JOBS_PAGE_SIZE = 8

# range_key -> (window hours, bucket count, strftime label)
RANGES: dict[str, tuple[int, int, str]] = {
    "24h": (24, 12, "%H:%M"),
    "7d": (24 * 7, 7, "%m-%d"),
    "30d": (24 * 30, 10, "%m-%d"),
}

_TEMPLATE_PATH = Path(__file__).resolve().parent / "dashboard.html"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "CodePickL0Dashboard/0.3"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_html(_render_index())
            return
        if parsed.path == "/api/status":
            params = parse_qs(parsed.query)
            offset = _int_param(params, "jobs_offset", 0)
            limit = _int_param(params, "jobs_limit", JOBS_PAGE_SIZE)
            range_key = params.get("range", ["24h"])[0] if params else "24h"
            if range_key not in RANGES:
                range_key = "24h"
            self._send_json(_status(range_key=range_key, jobs_offset=offset, jobs_limit=limit))
            return
        if parsed.path == "/api/source-types":
            self._send_json({"types": list_types()})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self._read_json()
        try:
            if parsed.path == "/api/sources":
                self._send_json(_create_source(body), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/api/sources/toggle":
                self._send_json(_toggle_source(body))
                return
            if parsed.path == "/api/crawl":
                self._send_json(_run_crawl(body))
                return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:  # surface pipeline errors to the UI
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: object) -> None:
        print(f"[dashboard] {self.address_string()} {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _send_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    values = params.get(key)
    if not values:
        return default
    try:
        return max(0, int(values[0]))
    except ValueError:
        return default


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _next_run_at(last_attempt_at: datetime | None, interval_min: int) -> str | None:
    last = _as_utc(last_attempt_at)
    if last is None:
        return None
    return (last + timedelta(minutes=interval_min)).isoformat(timespec="seconds")


def _scheduler_status(path: Path = HEARTBEAT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"running": False, "last_tick": None, "due": 0, "crawled": 0, "failed": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"running": False, "last_tick": None, "due": 0, "crawled": 0, "failed": 0}
    last_tick = payload.get("last_tick")
    running = False
    if isinstance(last_tick, str):
        try:
            ts = datetime.fromisoformat(last_tick)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            running = datetime.now(UTC) - ts <= timedelta(minutes=5)
        except ValueError:
            running = False
    return {
        "running": running,
        "last_tick": last_tick,
        "due": int(payload.get("due") or 0),
        "crawled": int(payload.get("crawled") or 0),
        "failed": int(payload.get("failed") or 0),
    }


def _series(session: Any, range_key: str) -> dict[str, Any]:
    hours, buckets, label_fmt = RANGES[range_key]
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    span = (now - start).total_seconds() or 1.0

    def bucketize(times: list[datetime | None]) -> list[int]:
        counts = [0] * buckets
        for raw in times:
            ts = _as_utc(raw)
            if ts is None or ts < start or ts > now:
                continue
            idx = int((ts - start).total_seconds() / span * buckets)
            counts[min(max(idx, 0), buckets - 1)] += 1
        return counts

    raw_times = list(
        session.scalars(
            select(RawDocument.fetched_at).order_by(RawDocument.fetched_at.desc()).limit(5000)
        ).all()
    )
    content_times = list(
        session.scalars(
            select(ContentItem.fetched_at).order_by(ContentItem.fetched_at.desc()).limit(5000)
        ).all()
    )
    labels = [
        (start + timedelta(seconds=span * (i + 1) / buckets)).strftime(label_fmt)
        for i in range(buckets)
    ]
    return {"labels": labels, "raw": bucketize(raw_times), "content": bucketize(content_times)}


def _status(
    *, range_key: str = "24h", jobs_offset: int = 0, jobs_limit: int = JOBS_PAGE_SIZE
) -> dict[str, Any]:
    jobs_limit = max(1, min(jobs_limit, 100))
    if range_key not in RANGES:
        range_key = "24h"
    with SessionLocal() as session:
        source_count = session.scalar(select(func.count()).select_from(Source)) or 0
        source_enabled = (
            session.scalar(
                select(func.count()).select_from(Source).where(Source.enabled.is_(True))
            )
            or 0
        )
        raw_count = session.scalar(select(func.count()).select_from(RawDocument)) or 0
        content_count = session.scalar(select(func.count()).select_from(ContentItem)) or 0
        version_count = session.scalar(select(func.count()).select_from(ContentVersion)) or 0
        outbox_total = session.scalar(select(func.count()).select_from(OutboxEvent)) or 0
        outbox_pending = (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
            )
            or 0
        )
        outbox_published = outbox_total - outbox_pending
        delivery_rate = round(outbox_published / outbox_total * 100, 1) if outbox_total else 100.0

        status_breakdown = {
            str(status): int(count)
            for status, count in session.execute(
                select(ContentItem.status, func.count()).group_by(ContentItem.status)
            ).all()
        }
        doc_counts = {
            sid: int(count)
            for sid, count in session.execute(
                select(RawDocument.source_id, func.count()).group_by(RawDocument.source_id)
            ).all()
        }

        jobs_total = session.scalar(select(func.count()).select_from(CrawlJob)) or 0
        crawl_jobs = session.scalars(
            select(CrawlJob)
            .order_by(CrawlJob.started_at.desc())
            .offset(jobs_offset)
            .limit(jobs_limit)
        ).all()
        contents = session.scalars(
            select(ContentItem).order_by(ContentItem.fetched_at.desc()).limit(12)
        ).all()
        sources = session.scalars(select(Source).order_by(Source.created_at.desc()).limit(50)).all()

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "range": range_key,
            "counts": {
                "sources": source_count,
                "sources_enabled": source_enabled,
                "raw_documents": raw_count,
                "content_items": content_count,
                "content_versions": version_count,
                "outbox_events": outbox_total,
                "outbox_published": outbox_published,
                "outbox_pending": outbox_pending,
                "delivery_rate": delivery_rate,
            },
            "series": _series(session, range_key),
            "status_breakdown": status_breakdown,
            "scheduler": _scheduler_status(),
            "sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "feed_url": source.feed_url,
                    "type": source.type,
                    "enabled": source.enabled,
                    "interval_min": int(source.crawl_config.get("interval_min") or 60),
                    "next_run": _next_run_at(
                        source.health.last_attempt_at if source.health else None,
                        int(source.crawl_config.get("interval_min") or 60),
                    ),
                    "doc_count": doc_counts.get(source.id, 0),
                    "health": (source.health.status if source.health else "unknown"),
                    "fail_count": (source.health.fail_count if source.health else 0),
                }
                for source in sources
            ],
            "recent_content": [
                {
                    "id": item.id,
                    "title": item.title,
                    "canonical_url": item.canonical_url,
                    "lang": item.lang,
                    "status": item.status,
                    "fetched_at": item.fetched_at,
                    "meta": item.meta,
                }
                for item in contents
            ],
            "recent_jobs": [
                {
                    "id": job.id,
                    "source_id": job.source_id,
                    "kind": job.kind,
                    "status": job.status,
                    "started_at": job.started_at,
                    "stats": job.stats,
                    "error": job.error,
                }
                for job in crawl_jobs
            ],
            "jobs_page": {
                "offset": jobs_offset,
                "limit": jobs_limit,
                "total": jobs_total,
                "has_prev": jobs_offset > 0,
                "has_next": jobs_offset + jobs_limit < jobs_total,
            },
        }


def _create_source(body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    feed_url = str(body.get("feed_url") or "").strip() or None
    home_url = str(body.get("home_url") or "").strip() or None
    source_type = str(body.get("type") or "rss").strip()
    crawl_config = body.get("crawl_config") or {}
    if not name:
        raise ValueError("name is required")
    if not isinstance(crawl_config, dict):
        raise ValueError("crawl_config must be an object")
    get_adapter(source_type)
    with SessionLocal() as session:
        source = create_source(
            session,
            name=name,
            feed_url=feed_url,
            home_url=home_url,
            source_type=source_type,
            crawl_config=crawl_config,
        )
        session.commit()
        return {
            "id": source.id,
            "name": source.name,
            "feed_url": source.feed_url,
            "type": source.type,
            "enabled": source.enabled,
        }


def _toggle_source(body: dict[str, Any]) -> dict[str, Any]:
    source_id = body.get("id")
    if not isinstance(source_id, int):
        raise ValueError("id must be an integer")
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise ValueError(f"source {source_id} not found")
        source.enabled = not source.enabled
        session.commit()
        return {"id": source.id, "enabled": source.enabled}


def _run_crawl(body: dict[str, Any]) -> dict[str, Any]:
    source_id = body.get("source_id")
    if not isinstance(source_id, int):
        raise ValueError("source_id must be an integer")
    settings = get_settings()
    store = build_object_store(settings)
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise ValueError(f"source {source_id} not found")
        stats = crawl_source(session, store, source)
        session.commit()
        return {"source_id": source_id, "stats": stats}


def _render_index() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    create_all(engine)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"L0 dashboard: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
