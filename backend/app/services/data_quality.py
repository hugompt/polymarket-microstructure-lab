"""Data-quality engine: classify every incoming tick/snapshot before it's trusted.

A ``FeedTracker`` keeps rolling per-feed state (last timestamp, last value, last hash, counters)
and returns a ``QualityResult`` flagging stale / duplicate / out-of-order / impossible-jump
events, plus suspicious first-ticks right after a reconnect. Trackers are pure/in-memory and
unit-testable; persistence of ``FeedHealth`` rows + ``DataQualityEvent`` rows is done by the
collector via the helpers here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import models
from ..util.timeutil import now_utc


@dataclass
class QualityResult:
    accepted: bool = True
    is_stale: bool = False
    is_duplicate: bool = False
    is_out_of_order: bool = False
    is_impossible: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.is_stale or self.is_duplicate or self.is_out_of_order or self.is_impossible


@dataclass
class FeedTracker:
    source: str
    key: str  # token_id or asset symbol
    asset_symbol: str | None = None
    market_id: int | None = None

    connected: bool = False
    last_value: float | None = None
    last_ts_epoch: float | None = None
    last_hash: str | None = None
    last_message_monotonic: float | None = None
    last_message_at: datetime | None = None
    reconnect_at_monotonic: float | None = None

    messages: int = 0
    duplicates: int = 0
    stale: int = 0
    out_of_order: int = 0
    gaps: int = 0
    reconnects: int = 0
    rejected: int = 0

    def on_control(self, event_type: str, count_reconnect: bool = True) -> None:
        # count_reconnect=False lets per-token trackers track connected state + the post-reconnect
        # grace window WITHOUT each one incrementing the reconnect counter (a single connection
        # drop should count once, not once per subscribed token).
        if event_type == "_connect":
            self.connected = True
        elif event_type == "_disconnect":
            self.connected = False
        elif event_type == "_reconnect":
            self.connected = False
            self.reconnect_at_monotonic = time.monotonic()
            if count_reconnect:
                self.reconnects += 1

    def assess(
        self,
        *,
        value: float | None,
        ts_epoch: float | None,
        hash_: str | None = None,
        received_at: datetime | None = None,
        max_jump: float | None = None,
        stale_after: float | None = None,
    ) -> QualityResult:
        received_at = received_at or now_utc()
        max_jump = settings.max_price_jump if max_jump is None else max_jump
        stale_after = settings.stale_after_seconds if stale_after is None else stale_after
        res = QualityResult()
        self.messages += 1
        self.connected = True
        now_mono = time.monotonic()

        # Duplicate: identical hash, or identical (value, ts) to the previous message.
        if hash_ is not None and self.last_hash is not None and hash_ == self.last_hash:
            res.is_duplicate = True
            res.reasons.append("duplicate hash")
        elif (
            value is not None and ts_epoch is not None
            and self.last_value == value and self.last_ts_epoch == ts_epoch
        ):
            res.is_duplicate = True
            res.reasons.append("duplicate value/ts")

        # Out-of-order: source timestamp goes backwards.
        if ts_epoch is not None and self.last_ts_epoch is not None and ts_epoch < self.last_ts_epoch:
            res.is_out_of_order = True
            res.reasons.append(f"out-of-order ts ({ts_epoch} < {self.last_ts_epoch})")

        # Impossible jump: value moved more than max_jump since last accepted value.
        if value is not None and self.last_value is not None:
            if abs(value - self.last_value) > max_jump:
                res.is_impossible = True
                res.reasons.append(f"impossible jump |Δ|={abs(value - self.last_value):.4f} > {max_jump}")

        # Stale: source timestamp far behind receive time.
        if ts_epoch is not None:
            age = received_at.timestamp() - ts_epoch
            if age > stale_after:
                res.is_stale = True
                res.reasons.append(f"stale {age:.1f}s > {stale_after}s")

        # Suspicious first tick shortly after a reconnect.
        if self.reconnect_at_monotonic is not None:
            if now_mono - self.reconnect_at_monotonic <= settings.reconnect_grace_seconds:
                if res.is_out_of_order or res.is_stale:
                    res.reasons.append("suspect first tick post-reconnect")
            else:
                self.reconnect_at_monotonic = None

        # Gap detection (long silence between messages on a live feed).
        if self.last_message_monotonic is not None:
            gap = now_mono - self.last_message_monotonic
            if gap > stale_after:
                self.gaps += 1
                res.reasons.append(f"gap {gap:.1f}s")

        # Accept policy: reject duplicates, out-of-order, and impossible jumps; keep stale (flagged).
        res.accepted = not (res.is_duplicate or res.is_out_of_order or res.is_impossible)

        # Update counters.
        if res.is_duplicate:
            self.duplicates += 1
        if res.is_out_of_order:
            self.out_of_order += 1
        if res.is_stale:
            self.stale += 1
        if not res.accepted:
            self.rejected += 1

        # Update rolling state only from accepted, sane values.
        if res.accepted and value is not None:
            self.last_value = value
        if res.accepted and ts_epoch is not None:
            self.last_ts_epoch = ts_epoch
        if hash_ is not None:
            self.last_hash = hash_
        self.last_message_monotonic = now_mono
        self.last_message_at = received_at
        return res

    def health_dict(self) -> dict:
        age = None
        if self.last_message_at is not None:
            age = (now_utc() - self.last_message_at).total_seconds()
        dup_rate = self.duplicates / self.messages if self.messages else 0.0
        stale_rate = self.stale / self.messages if self.messages else 0.0
        ooo_rate = self.out_of_order / self.messages if self.messages else 0.0
        # Simple 0..1 health score: penalise disconnection, staleness, dup/ooo.
        score = 1.0
        if not self.connected:
            score -= 0.5
        score -= min(0.3, stale_rate)
        score -= min(0.1, dup_rate)
        score -= min(0.1, ooo_rate)
        return {
            "source": self.source,
            "token_id": self.key if self.source.startswith("clob") else None,
            "asset_symbol": self.asset_symbol,
            "connected": self.connected,
            "last_message_age_s": round(age, 2) if age is not None else None,
            "messages": self.messages,
            "duplicates": self.duplicates,
            "stale": self.stale,
            "out_of_order": self.out_of_order,
            "gaps": self.gaps,
            "reconnects": self.reconnects,
            "rejected": self.rejected,
            "duplicate_rate": round(dup_rate, 4),
            "stale_rate": round(stale_rate, 4),
            "health_score": round(max(0.0, min(1.0, score)), 3),
        }


def record_quality_event(
    db: Session, tracker: FeedTracker, event_type: str, message: str, detail: dict | None = None,
    severity: str = "warn",
) -> None:
    db.add(models.DataQualityEvent(
        ts=now_utc(),
        market_id=tracker.market_id,
        token_id=tracker.key if tracker.source.startswith("clob") else None,
        asset_symbol=tracker.asset_symbol,
        source=tracker.source,
        event_type=event_type,
        severity=severity,
        message=message,
        detail=detail,
    ))


def upsert_feed_health(db: Session, tracker: FeedTracker) -> None:
    token_id = tracker.key if tracker.source.startswith("clob") else None
    asset = tracker.asset_symbol
    row = db.scalar(
        select(models.FeedHealth).where(
            models.FeedHealth.source == tracker.source,
            models.FeedHealth.token_id.is_(token_id) if token_id is None else models.FeedHealth.token_id == token_id,
            models.FeedHealth.asset_symbol.is_(asset) if asset is None else models.FeedHealth.asset_symbol == asset,
        )
    )
    if row is None:
        row = models.FeedHealth(source=tracker.source, token_id=token_id, asset_symbol=asset)
        db.add(row)
    row.market_id = tracker.market_id
    row.connected = tracker.connected
    row.last_message_at = tracker.last_message_at
    row.messages = tracker.messages
    row.duplicates = tracker.duplicates
    row.stale = tracker.stale
    row.out_of_order = tracker.out_of_order
    row.gaps = tracker.gaps
    row.reconnects = tracker.reconnects
    row.rejected = tracker.rejected
    row.updated_at = now_utc()
