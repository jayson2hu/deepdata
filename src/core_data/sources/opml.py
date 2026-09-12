from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from sqlalchemy.orm import Session

from core_data.sources.repository import create_source


def import_opml(session: Session, path: str | Path) -> int:
    root = ET.parse(path).getroot()
    imported = 0
    for outline in root.findall(".//outline"):
        feed_url = outline.attrib.get("xmlUrl")
        if not feed_url:
            continue
        try:
            create_source(
                session,
                name=outline.attrib.get("title") or outline.attrib.get("text") or feed_url,
                feed_url=feed_url,
                home_url=outline.attrib.get("htmlUrl"),
            )
            imported += 1
        except ValueError:
            continue
    return imported
