from __future__ import annotations

from sqlalchemy import Engine, text

from core_data.db.models import Base


def create_all(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
