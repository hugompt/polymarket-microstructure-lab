"""SQLAlchemy declarative base + cross-dialect JSON type.

JSONB on PostgreSQL, plain JSON on SQLite, so raw payloads (rule 11) round-trip
everywhere. All raw API responses are stored verbatim for reproducibility.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Integer, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..util.timeutil import now_utc

# JSONB on Postgres, JSON elsewhere (SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")
# BigInteger that degrades to Integer on SQLite (which has no real bigint distinction).
BigInt = BigInteger().with_variant(Integer(), "sqlite")


class UTCDateTime(TypeDecorator):
    """tz-aware UTC datetimes, consistently.

    SQLite's DateTime stores naive strings (dropping tzinfo), which otherwise yields
    naive-vs-aware comparison errors and offset-format mismatches in range filters. This
    decorator normalises every value to UTC on bind and re-attaches UTC on load, so Python
    always sees aware-UTC and the DB always stores a consistent UTC wall-clock. Works the
    same on PostgreSQL (timestamptz).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=now_utc, nullable=False
    )
