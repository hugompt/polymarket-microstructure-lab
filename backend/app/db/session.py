"""Engine + session management. Sync SQLAlchemy (works identically for SQLite & Postgres).

FastAPI sync handlers run in a threadpool, so a sync Session is the pragmatic, robust
choice for this read-heavy research tool.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    engine = create_engine(
        url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=not url.startswith("sqlite"),
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, class_=Session, future=True
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency (read-only by default; routers don't write)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
