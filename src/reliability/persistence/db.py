"""Engine / session factory (SQLite, WAL)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from reliability.persistence.models import Base


def make_engine(db_path: str | Path) -> Engine:
    if str(db_path) == ":memory:":
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    Base.metadata.create_all(engine)
    if str(db_path) != ":memory:":
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(analysis)")}
            if "media_type" not in cols:
                conn.exec_driver_sql("ALTER TABLE analysis ADD COLUMN media_type VARCHAR(32)")
            if "media_url" not in cols:
                conn.exec_driver_sql("ALTER TABLE analysis ADD COLUMN media_url TEXT")
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
