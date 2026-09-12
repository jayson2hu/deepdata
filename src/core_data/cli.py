from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from core_data.config import get_settings
from core_data.db.bootstrap import create_all
from core_data.db.models import Source
from core_data.db.session import SessionLocal, engine
from core_data.ingest.pipeline import crawl_source
from core_data.sources.opml import import_opml
from core_data.storage.factory import build_object_store


def main() -> None:
    parser = argparse.ArgumentParser(prog="core-data")
    sub = parser.add_subparsers(dest="command", required=True)
    source_parser = sub.add_parser("source")
    source_sub = source_parser.add_subparsers(dest="source_command", required=True)
    source_import = source_sub.add_parser("import")
    source_import.add_argument("path")
    ingest = sub.add_parser("ingest")
    ingest_sub = ingest.add_subparsers(dest="ingest_command", required=True)
    run = ingest_sub.add_parser("run")
    run.add_argument("--all", action="store_true")
    args = parser.parse_args()

    create_all(engine)
    settings = get_settings()
    store = build_object_store(settings)
    with SessionLocal() as session:
        if args.command == "source" and args.source_command == "import":
            count = import_opml(session, Path(args.path))
            session.commit()
            print(f"imported={count}")
            return
        if args.command == "ingest" and args.ingest_command == "run" and args.all:
            sources = session.scalars(select(Source).where(Source.enabled.is_(True))).all()
            total = {"entries": 0, "raw": 0, "content": 0, "failed": 0}
            for source_obj in sources:
                stats = crawl_source(session, store, source_obj)
                for key, value in stats.items():
                    total[key] += value
            session.commit()
            print(total)
            return
    raise SystemExit(2)


if __name__ == "__main__":
    main()
