"""CLOB market WebSocket channel (public): live orderbook, price changes, last trade.

Subscribes by token (asset) ids. Message event types observed: ``book`` (full snapshot),
``price_change`` (deltas), ``tick_size_change``, ``last_trade_price``. Unknown types are
emitted as ``unknown`` (and logged) instead of crashing (tolerant clients requirement).
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..util.timeutil import epoch_to_utc, now_utc
from .ws_base import BaseWSClient

KNOWN_EVENTS = {"book", "price_change", "tick_size_change", "last_trade_price"}


class ClobMarketWS(BaseWSClient):
    name = "clob_ws"

    def __init__(self, token_ids: list[str], *, url: str | None = None):
        super().__init__(url or settings.clob_ws_url, ping_text="PING", ping_interval=10.0)
        self.token_ids = [str(t) for t in token_ids if t]

    def subscribe_messages(self) -> list[dict | str]:
        # Send both the documented and legacy key shapes for tolerance.
        return [{"assets_ids": self.token_ids, "type": "market"}]

    def parse(self, raw: Any) -> list[dict]:
        if isinstance(raw, dict) and ("_control" in raw or "_unparsed" in raw):
            return []
        events = raw if isinstance(raw, list) else [raw]
        out: list[dict] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            etype = ev.get("event_type") or ev.get("type") or "unknown"
            token = ev.get("asset_id") or ev.get("token_id") or ev.get("asset")
            condition = ev.get("market") or ev.get("condition_id")
            src_ts = ev.get("timestamp") or ev.get("ts")
            normalized = {
                "event_type": etype if etype in KNOWN_EVENTS else "unknown",
                "raw_event_type": etype,
                "source": "clob_ws",
                "token_id": str(token) if token is not None else None,
                "condition_id": condition,
                "source_ts": epoch_to_utc(_ms_to_s(src_ts)),
                "received_ts": now_utc(),
                "payload": ev,
            }
            if etype in ("book",):
                normalized["bids"] = ev.get("bids") or ev.get("buys") or []
                normalized["asks"] = ev.get("asks") or ev.get("sells") or []
                normalized["book_hash"] = ev.get("hash")
            if etype in ("price_change",):
                normalized["changes"] = ev.get("changes") or ev.get("price_changes") or []
            if etype in ("last_trade_price",):
                normalized["price"] = _f(ev.get("price"))
                normalized["size"] = _f(ev.get("size"))
                normalized["side"] = ev.get("side")
            out.append(normalized)
        return out


def _ms_to_s(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f / 1000.0 if f > 1e12 else f


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
