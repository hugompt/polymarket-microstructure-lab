"""Market parser for Polymarket crypto Up/Down markets.

Slug grammar (observed):   ``{asset}-updown-{minutes}m-{unix_start}``
  e.g. ``btc-updown-15m-1782149400``, ``xrp-updown-5m-1782287100``
Title grammar (observed):  ``Bitcoin Up or Down - June 24, 3:45AM-4:00AM ET``

Detection is multi-signal: slug, title, outcomes (Up/Down), and event tags. If the asset or
window can't be determined confidently the market is still kept with ``parse_status =
"uncertain"`` and a note explaining why (rule: never silently drop a market).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..util.normalize import as_json_list, to_float
from ..util.timeutil import epoch_to_utc, now_utc, parse_any_time

# slug asset-prefix -> canonical symbol (extend freely; configurable universe lives in settings)
SLUG_ASSET_MAP = {
    "btc": "BTC", "bitcoin": "BTC", "xbt": "BTC",
    "eth": "ETH", "ethereum": "ETH",
    "sol": "SOL", "solana": "SOL",
    "xrp": "XRP", "ripple": "XRP",
    "doge": "DOGE", "dogecoin": "DOGE",
    "bnb": "BNB", "matic": "MATIC", "avax": "AVAX", "ltc": "LTC",
    "link": "LINK", "ada": "ADA", "hype": "HYPE", "hyperliquid": "HYPE",
    "pepe": "PEPE", "trx": "TRX", "ton": "TON", "sui": "SUI",
}
# Title words -> symbol
TITLE_ASSET_MAP = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP", "xrp": "XRP",
    "dogecoin": "DOGE", "doge": "DOGE", "hyperliquid": "HYPE", "bnb": "BNB",
}

SLUG_RE = re.compile(r"(?P<asset>[a-z0-9]+)-(?:up-?down|updown)-(?P<win>\d+)m-(?P<ts>\d+)", re.I)
UPDOWN_HINT = re.compile(r"up\s*or\s*down|up-?down", re.I)


@dataclass
class MarketParse:
    asset_symbol: str | None = None
    window_minutes: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    start_epoch: int | None = None
    end_epoch: int | None = None
    outcomes: list = field(default_factory=list)
    clob_token_ids: list = field(default_factory=list)
    up_token_id: str | None = None
    down_token_id: str | None = None
    status: str = "unknown"
    resolved_outcome: str | None = None
    parse_status: str = "ok"
    parse_notes: str | None = None
    is_crypto_updown: bool = False


def _asset_from_slug(slug: str | None) -> str | None:
    if not slug:
        return None
    m = SLUG_RE.search(slug)
    if m:
        return SLUG_ASSET_MAP.get(m.group("asset").lower(), m.group("asset").upper())
    return None


def _asset_from_title(title: str | None) -> str | None:
    if not title:
        return None
    low = title.lower()
    for word, sym in TITLE_ASSET_MAP.items():
        if word in low:
            return sym
    return None


def looks_like_crypto_updown(raw: dict, event: dict | None = None) -> bool:
    slug = (raw.get("slug") or "").lower()
    title = raw.get("question") or raw.get("title") or ""
    ev_slug = (event or {}).get("slug", "") or raw.get("eventSlug", "") or ""
    if SLUG_RE.search(slug) or SLUG_RE.search(ev_slug):
        return True
    outcomes = [str(o).lower() for o in as_json_list(raw.get("outcomes"))]
    if UPDOWN_HINT.search(title) and {"up", "down"} <= set(outcomes):
        return True
    return False


def parse_market(raw: dict, event: dict | None = None, now: datetime | None = None) -> MarketParse:
    now = now or now_utc()
    p = MarketParse()
    notes: list[str] = []

    slug = raw.get("slug") or ""
    ev_slug = (event or {}).get("slug") if event else raw.get("eventSlug")
    title = raw.get("question") or raw.get("title") or (event or {}).get("title")

    # --- asset + window from slug, fall back to event slug then title ---
    m = SLUG_RE.search(slug) or (SLUG_RE.search(ev_slug or ""))
    if m:
        p.asset_symbol = SLUG_ASSET_MAP.get(m.group("asset").lower(), m.group("asset").upper())
        p.window_minutes = int(m.group("win"))
        p.start_epoch = int(m.group("ts"))
        p.start_time = epoch_to_utc(p.start_epoch)
    else:
        p.asset_symbol = _asset_from_slug(slug) or _asset_from_title(title)
        if p.asset_symbol is None:
            notes.append("asset not derivable from slug/title")

    # --- times ---
    # For crypto Up/Down markets the SLUG is authoritative: it encodes the exact window start,
    # and end = start + window. Gamma's startDate is merely the listing time and its endDate is
    # frequently the WRONG DAY for these rapid markets (observed: a 5-minute market with an
    # endDate ~24h out). So when the slug matched, we trust it and IGNORE Gamma's start/end.
    # We only fall back to Gamma's fields when the slug did not give us a start/window.
    slug_derived = m is not None
    gamma_start = parse_any_time(raw.get("startDate") or raw.get("startDateIso") or raw.get("startTime"))
    gamma_end = parse_any_time(raw.get("endDate") or raw.get("endDateIso"))
    if not slug_derived:
        if gamma_start:
            p.start_time = gamma_start
            p.start_epoch = int(gamma_start.timestamp())
        if gamma_end:
            p.end_time = gamma_end
            p.end_epoch = int(gamma_end.timestamp())
    if p.end_time is None and p.start_time is not None and p.window_minutes:
        p.end_time = epoch_to_utc(p.start_time.timestamp() + p.window_minutes * 60)
        p.end_epoch = int(p.end_time.timestamp())
    if p.window_minutes is None and p.start_time and p.end_time:
        mins = round((p.end_time - p.start_time).total_seconds() / 60)
        p.window_minutes = mins if mins > 0 else None
        if p.window_minutes:
            notes.append("window inferred from start/end")
            # A 5m/15m microstructure market should never infer a multi-hour window. If it does,
            # this is a longer-dated crypto market caught by the title heuristic -> flag uncertain.
            if p.window_minutes > 60:
                p.parse_status = "uncertain"
                notes.append("inferred window implausibly large for a 5m/15m market")

    # --- outcomes + token ids ---
    p.outcomes = [str(o) for o in as_json_list(raw.get("outcomes"))]
    p.clob_token_ids = [str(t) for t in as_json_list(raw.get("clobTokenIds"))]
    if p.outcomes and p.clob_token_ids and len(p.outcomes) == len(p.clob_token_ids):
        for name, tok in zip(p.outcomes, p.clob_token_ids):
            low = name.strip().lower()
            if low == "up":
                p.up_token_id = tok
            elif low == "down":
                p.down_token_id = tok
        if p.up_token_id is None and len(p.clob_token_ids) == 2:
            # Fall back to positional [Up, Down].
            p.up_token_id, p.down_token_id = p.clob_token_ids[0], p.clob_token_ids[1]
            notes.append("Up/Down token mapping assumed positional")
    elif p.clob_token_ids:
        notes.append("outcomes/token-id length mismatch")

    # --- resolution (closed markets carry outcomePrices ~ [1,0]) ---
    prices = [to_float(x) for x in as_json_list(raw.get("outcomePrices"))]
    closed = bool(raw.get("closed"))
    if closed and prices and p.outcomes and len(prices) == len(p.outcomes):
        winners = [p.outcomes[i] for i, pr in enumerate(prices) if pr is not None and pr >= 0.99]
        if len(winners) == 1:
            p.resolved_outcome = winners[0]

    # --- status classification ---
    p.status = _classify_status(raw, p, now)

    p.is_crypto_updown = looks_like_crypto_updown(raw, event)
    if p.asset_symbol is None or p.window_minutes is None:
        p.parse_status = "uncertain"
    if notes:
        p.parse_notes = "; ".join(notes)
        if "assumed" in p.parse_notes and p.parse_status == "ok":
            p.parse_status = "ok"  # assumption noted but still usable
    return p


def _classify_status(raw: dict, p: MarketParse, now: datetime) -> str:
    if raw.get("archived"):
        return "resolved" if p.resolved_outcome else "ended"
    if p.resolved_outcome is not None:
        return "resolved"
    closed = bool(raw.get("closed"))
    active = raw.get("active")
    if p.start_time and p.end_time:
        if now < p.start_time:
            return "upcoming"
        if p.start_time <= now <= p.end_time:
            return "ended" if closed else "live"
        if now > p.end_time:
            return "resolved" if closed else "ended"
    if closed:
        return "ended"
    if active and raw.get("acceptingOrders"):
        return "live"
    return "unknown"
