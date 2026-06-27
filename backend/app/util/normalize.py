"""Generic normalization helpers shared across services & analysis.

Pure functions, no DB/network — easy to unit test.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# ---- numbers ----


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_json_list(value: Any) -> list:
    """Gamma returns ``outcomes`` / ``clobTokenIds`` / ``outcomePrices`` as JSON *strings*.
    Accept either a real list or a JSON-encoded string."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [s]
    return [value]


def dedup_hash(*parts: Any) -> str:
    """Stable short hash for idempotent upserts (trades, activity, snapshots)."""
    payload = json.dumps([_norm(p) for p in parts], sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:32]


def _norm(p: Any) -> Any:
    if isinstance(p, float):
        # Avoid float-repr drift in hashes.
        return round(p, 8)
    return p


# ---- price buckets (entry-price analysis) ----

# (low_inclusive, high_exclusive, label)
PRICE_BUCKETS: list[tuple[float, float, str]] = [
    (0.00, 0.05, "0-5"),
    (0.05, 0.15, "5-15"),
    (0.15, 0.35, "15-35"),
    (0.35, 0.50, "35-50"),
    (0.50, 0.65, "50-65"),
    (0.65, 0.85, "65-85"),
    (0.85, 0.95, "85-95"),
    (0.95, 1.0001, "95-100"),
]

BUCKET_ORDER = [b[2] for b in PRICE_BUCKETS]


def price_bucket(price: float | None) -> str | None:
    if price is None:
        return None
    p = max(0.0, min(1.0, float(price)))
    for lo, hi, label in PRICE_BUCKETS:
        if lo <= p < hi:
            return label
    return PRICE_BUCKETS[-1][2]


# ---- orderbook normalization ----


def _levels(raw_levels: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for lvl in raw_levels or []:
        if isinstance(lvl, dict):
            price = to_float(lvl.get("price"))
            size = to_float(lvl.get("size"))
        elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
            price, size = to_float(lvl[0]), to_float(lvl[1])
        else:
            continue
        if price is not None and size is not None:
            out.append((price, size))
    return out


def normalize_book(bids: Any, asks: Any) -> dict:
    """Compute best bid/ask, mid, spread, and top-5/10 depth from raw level arrays.

    CLOB returns bids ascending and asks descending; we sort defensively so best bid is the
    highest bid price and best ask is the lowest ask price regardless of input order.
    """
    bid_lvls = sorted(_levels(bids), key=lambda x: x[0], reverse=True)   # high -> low
    ask_lvls = sorted(_levels(asks), key=lambda x: x[0])                  # low -> high

    best_bid = bid_lvls[0][0] if bid_lvls else None
    best_ask = ask_lvls[0][0] if ask_lvls else None
    mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None

    def depth(levels: list[tuple[float, float]], n: int) -> float:
        return round(sum(s for _, s in levels[:n]), 6)

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread": spread,
        "bid_depth_top5": depth(bid_lvls, 5),
        "ask_depth_top5": depth(ask_lvls, 5),
        "bid_depth_top10": depth(bid_lvls, 10),
        "ask_depth_top10": depth(ask_lvls, 10),
        "bid_levels": bid_lvls,
        "ask_levels": ask_lvls,
    }


def orderbook_imbalance(book: dict) -> float | None:
    """(bid_depth - ask_depth) / (bid_depth + ask_depth) over top-5. Range [-1, 1]."""
    b = book.get("bid_depth_top5") or 0.0
    a = book.get("ask_depth_top5") or 0.0
    total = b + a
    if total <= 0:
        return None
    return (b - a) / total
