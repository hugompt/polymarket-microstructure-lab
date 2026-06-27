"""Market replay series builder (shared by the API replay endpoint and CSV export).

Builds time series for a single market: Up/Down price, best bid/ask/spread, Binance &
Chainlink spot, and overlaid tracked-wallet trades, plus the resolution. Uses recorded
orderbook snapshots & ticks first; if no book was recorded it can optionally backfill the
price series from the public CLOB ``/prices-history`` endpoint so replay is useful even
before the live collector has run on that market.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clients.clob import ClobClient
from ..db import models
from ..logging_conf import get_logger
from ..util.timeutil import epoch_to_utc, to_utc

log = get_logger("services.replay")


def _iso(dt):
    return to_utc(dt).isoformat() if dt else None


def resolve_market(db: Session, market_ref: str | int) -> models.Market | None:
    if isinstance(market_ref, int) or str(market_ref).isdigit():
        m = db.get(models.Market, int(market_ref))
        if m:
            return m
    return db.scalar(select(models.Market).where(models.Market.slug == str(market_ref)))


def _stored_price_series(db: Session, market: models.Market) -> list[dict]:
    up_tok, down_tok = market.up_token_id, market.down_token_id
    series: dict[str, dict] = {}
    if up_tok:
        for s in db.scalars(select(models.OrderbookSnapshot).where(
            models.OrderbookSnapshot.token_id == up_tok).order_by(
            models.OrderbookSnapshot.received_ts.asc())):
            if s.mid is not None:
                series.setdefault(_iso(s.received_ts), {})["up"] = s.mid
    if down_tok:
        for s in db.scalars(select(models.OrderbookSnapshot).where(
            models.OrderbookSnapshot.token_id == down_tok).order_by(
            models.OrderbookSnapshot.received_ts.asc())):
            if s.mid is not None:
                series.setdefault(_iso(s.received_ts), {})["down"] = s.mid
    return [{"t": t, **v} for t, v in sorted(series.items())]


def _stored_book_series(db: Session, market: models.Market) -> list[dict]:
    tok = market.up_token_id
    if not tok:
        return []
    out = []
    for s in db.scalars(select(models.OrderbookSnapshot).where(
        models.OrderbookSnapshot.token_id == tok).order_by(
        models.OrderbookSnapshot.received_ts.asc())):
        out.append({"t": _iso(s.received_ts), "bid": s.best_bid, "ask": s.best_ask,
                    "mid": s.mid, "spread": s.spread})
    return out


def _tick_series(db: Session, market: models.Market, source: str) -> list[dict]:
    if not market.asset_symbol or not market.start_time or not market.end_time:
        return []
    rows = db.scalars(select(models.CryptoPriceTick).where(
        models.CryptoPriceTick.asset_symbol == market.asset_symbol,
        models.CryptoPriceTick.source == source,
        models.CryptoPriceTick.received_ts >= market.start_time,
        models.CryptoPriceTick.received_ts <= market.end_time,
    ).order_by(models.CryptoPriceTick.received_ts.asc()))
    return [{"t": _iso(r.received_ts), "p": r.price} for r in rows]


def _wallet_trades(db: Session, market: models.Market) -> list[dict]:
    rows = db.scalars(select(models.Trade).where(models.Trade.market_id == market.id)
                      .order_by(models.Trade.ts_utc.asc()))
    return [{"t": _iso(r.ts_utc), "wallet": r.wallet_address, "side": r.side,
             "outcome": r.outcome, "price": r.price, "size": r.size} for r in rows]


async def _fetch_clob_history(up_tok: str | None, down_tok: str | None,
                              start_ts: int | None, end_ts: int | None) -> list[dict]:
    client = ClobClient()
    series: dict[int, dict] = {}
    try:
        for tok, side in ((up_tok, "up"), (down_tok, "down")):
            if not tok:
                continue
            try:
                hist = await client.prices_history(
                    tok, start_ts=start_ts, end_ts=end_ts,
                    interval=None if start_ts else "max", fidelity=1)
            except Exception as exc:
                log.debug("replay_history_error", error=str(exc))
                continue
            for pt in hist:
                t = pt.get("t")
                if t is None:
                    continue
                series.setdefault(int(t), {})[side] = pt.get("p")
    finally:
        await client.aclose()
    return [{"t": _iso(epoch_to_utc(t)), **v} for t, v in sorted(series.items())]


def build_replay(db: Session, market_ref: str | int, *, fetch_live: bool = True) -> dict | None:
    market = resolve_market(db, market_ref)
    if market is None:
        return None
    price_series = _stored_price_series(db, market)
    book_series = _stored_book_series(db, market)
    if not price_series and fetch_live:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop -> safe to drive a fresh one for the live history fetch.
            price_series = asyncio.run(_fetch_clob_history(
                market.up_token_id, market.down_token_id,
                market.start_epoch, market.end_epoch)) or []
        else:
            # Called from inside an async context -> skip the sync live fetch (don't crash).
            price_series = []

    return {
        "market": {
            "id": market.id, "slug": market.slug, "title": market.title,
            "asset": market.asset_symbol, "window_minutes": market.window_minutes,
            "status": market.status, "start_time": _iso(market.start_time),
            "end_time": _iso(market.end_time), "condition_id": market.condition_id,
        },
        "resolution": {"resolved_outcome": market.resolved_outcome, "status": market.status},
        "series": {
            "price": price_series,
            "book": book_series,
            "binance": _tick_series(db, market, "binance"),
            "chainlink": _tick_series(db, market, "chainlink"),
        },
        "wallet_trades": _wallet_trades(db, market),
    }
