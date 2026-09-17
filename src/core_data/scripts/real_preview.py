from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_data.db.bootstrap import create_all
from core_data.db.models import ContentItem, RawDocument, Source
from core_data.db.session import create_db_engine
from core_data.ingest.pipeline import crawl_source
from core_data.sources.repository import create_source
from core_data.storage.object_store import FileObjectStore


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list) or not sources:
        raise ValueError("manifest must contain a non-empty sources list")
    return [dict(item) for item in sources if isinstance(item, dict)]


def _source_report(session: Session, source: Source, stats: dict[str, int]) -> dict[str, Any]:
    errors = [
        {
            "url": raw.url,
            "error": raw.extra.get("error"),
        }
        for raw in session.scalars(
            select(RawDocument)
            .where(RawDocument.source_id == source.id)
            .where(RawDocument.fetch_method == "error")
            .order_by(RawDocument.id)
        )
    ]
    return {
        "source_id": source.id,
        "name": source.name,
        "home_url": source.home_url,
        "feed_url": source.feed_url,
        "stats": stats,
        "errors": errors,
    }


def run(
    *,
    data_dir: Path,
    manifest_path: Path,
    report_path: Path,
    max_items_per_source: int | None = None,
    reuse: bool = False,
) -> dict[str, Any]:
    if data_dir.exists() and not reuse:
        raise FileExistsError(f"data directory already exists: {data_dir}")
    data_dir.mkdir(parents=True, exist_ok=reuse)
    object_root = data_dir / "objects"
    database_path = data_dir / "l0.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_all(engine)
    object_store = FileObjectStore(object_root)
    source_reports: list[dict[str, Any]] = []
    source_failures: list[dict[str, str]] = []

    try:
        for definition in _load_manifest(manifest_path):
            name = str(definition.get("name") or "").strip()
            feed_url = str(definition.get("feed_url") or "").strip()
            if not name or not feed_url:
                source_failures.append(
                    {"name": name or "<missing>", "error": "name and feed_url are required"}
                )
                continue
            config = dict(definition.get("crawl_config") or {})
            if max_items_per_source is not None:
                config["max_entries"] = max_items_per_source
            with Session(engine) as session:
                source = session.scalar(select(Source).where(Source.feed_url == feed_url))
                if source is None:
                    source = create_source(
                        session,
                        name=name,
                        feed_url=feed_url,
                        home_url=str(definition.get("home_url") or "") or None,
                        source_type=str(definition.get("type") or "rss"),
                        crawl_config=config,
                    )
                else:
                    source.name = name
                    source.home_url = str(definition.get("home_url") or "") or None
                    source.type = str(definition.get("type") or "rss")
                    source.crawl_config = config
                source.etiquette = dict(definition.get("etiquette") or {})
                session.commit()
                source_id = source.id
            try:
                with Session(engine) as session:
                    source = session.get(Source, source_id)
                    if source is None:
                        raise LookupError(f"source disappeared: {source_id}")
                    stats = crawl_source(session, object_store, source)
                    session.commit()
                    source_reports.append(_source_report(session, source, stats))
            except Exception as exc:
                source_failures.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

        with Session(engine) as session:
            rows = session.scalars(select(ContentItem).order_by(ContentItem.id)).all()
            sources = {row.id: row for row in session.scalars(select(Source)).all()}
            items = [
                {
                    "content_id": item.id,
                    "source_id": item.source_id,
                    "source_name": (
                        sources[item.source_id].name if item.source_id in sources else None
                    ),
                    "canonical_url": item.canonical_url,
                    "title": item.title,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "fetched_at": item.fetched_at.isoformat(),
                    "content_version": item.current_version,
                    "content_hash": item.content_hash,
                    "text_chars": (
                        len(object_store.get_bytes(item.clean_text_ref).decode("utf-8"))
                        if item.clean_text_ref
                        else 0
                    ),
                }
                for item in rows
            ]
    finally:
        engine.dispose()

    totals = {
        "sources_requested": len(source_reports) + len(source_failures),
        "sources_succeeded": len(source_reports),
        "sources_failed": len(source_failures),
        "entries": sum(item["stats"]["entries"] for item in source_reports),
        "content": len(items),
        "failed_pages": sum(item["stats"]["failed"] for item in source_reports),
        "rejected_pages": sum(item["stats"].get("rejected", 0) for item in source_reports),
    }
    report = {
        "schema_version": 1,
        "kind": "codepick-l0-real-public-preview",
        "created_at": datetime.now(UTC).isoformat(),
        "database_url": f"sqlite:///{database_path}",
        "object_store": str(object_root),
        "reused_data_dir": reuse,
        "manifest": str(manifest_path.resolve()),
        "totals": totals,
        "sources": source_reports,
        "source_failures": source_failures,
        "items": items,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not items:
        raise RuntimeError(f"real preview produced no content; inspect {report_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a bounded public-source L0 preview")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-items-per-source", type=int)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    if args.max_items_per_source is not None and args.max_items_per_source <= 0:
        parser.error("--max-items-per-source must be positive")
    report = run(
        data_dir=args.data_dir,
        manifest_path=args.manifest,
        report_path=args.report,
        max_items_per_source=args.max_items_per_source,
        reuse=args.reuse,
    )
    print(
        "L0 REAL PREVIEW: "
        f"sources={report['totals']['sources_succeeded']}/"
        f"{report['totals']['sources_requested']} "
        f"content={report['totals']['content']} "
        f"failed_pages={report['totals']['failed_pages']}"
    )


if __name__ == "__main__":
    main()
