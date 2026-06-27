"""UTC time helpers. Rule 10: UTC everywhere.

Polymarket slugs and the Data API use Unix epoch *seconds*. The Gamma API uses ISO-8601
strings (often with 'Z'). Everything in our DB is stored as tz-aware UTC datetimes and/or
epoch-second integers. These helpers are the single conversion point.
"""
from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def now_epoch() -> float:
    return now_utc().timestamp()


def to_utc(dt: datetime) -> datetime:
    """Coerce any datetime to tz-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def epoch_to_utc(epoch_seconds: float | int | str | None) -> datetime | None:
    if epoch_seconds is None or epoch_seconds == "":
        return None
    try:
        val = float(epoch_seconds)
    except (TypeError, ValueError):
        return None
    # Tolerate millisecond timestamps (heuristic: > year ~2200 in seconds).
    if val > 4_102_444_800:  # 2100-01-01 in seconds
        val = val / 1000.0
    return datetime.fromtimestamp(val, tz=UTC)


def iso_to_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return to_utc(dt)
    except ValueError:
        return None


def parse_any_time(value) -> datetime | None:
    """Best-effort parse of either an epoch number or an ISO string into UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    if isinstance(value, (int, float)):
        return epoch_to_utc(value)
    s = str(value).strip()
    if not s:
        return None
    if s.replace(".", "", 1).isdigit():
        return epoch_to_utc(s)
    return iso_to_utc(s)
