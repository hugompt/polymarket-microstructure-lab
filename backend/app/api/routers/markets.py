from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import settings
from ...db import models
from ...db.session import get_db
from ...services.replay import build_replay
from ...util.timeutil import now_utc, to_utc

router = APIRouter(tags=["markets"])

LIVE_LIMIT = 300


def _latest_up_snapshot(db: Session, market: models.Market) -> models.OrderbookSnapshot | None:
    if not market.up_token_id:
        return None
    return db.scalars(
        select(models.OrderbookSnapshot)
        .where(models.OrderbookSnapshot.token_id == market.up_token_id)
        .order_by(models.OrderbookSnapshot.received_ts.desc()).limit(1)
    ).first()


def _latest_snapshots(db: Session, token_ids: list[str]) -> dict[str, models.OrderbookSnapshot]:
    """One batched query for the latest snapshot per token (avoids N+1 over the universe)."""
    token_ids = [t for t in token_ids if t]
    if not token_ids:
        return {}
    mrt = (select(models.OrderbookSnapshot.token_id,
                  func.max(models.OrderbookSnapshot.received_ts).label("mrt"))
           .where(models.OrderbookSnapshot.token_id.in_(token_ids))
           .group_by(models.OrderbookSnapshot.token_id)).subquery()
    rows = db.scalars(
        select(models.OrderbookSnapshot).join(
            mrt,
            (models.OrderbookSnapshot.token_id == mrt.c.token_id)
            & (models.OrderbookSnapshot.received_ts == mrt.c.mrt),
        )
    ).all()
    out: dict[str, models.OrderbookSnapshot] = {}
    for s in rows:
        out[s.token_id] = s  # ties resolve to one; acceptable for a top-of-book display
    return out


def market_row(db: Session, m: models.Market,
               snap: models.OrderbookSnapshot | None = None,
               _prefetched: bool = False) -> dict:
    if snap is None and not _prefetched:
        snap = _latest_up_snapshot(db, m)
    now = now_utc()
    up_price = snap.mid if snap and snap.mid is not None else m.last_trade_price
    best_bid = snap.best_bid if snap else m.best_bid
    best_ask = snap.best_ask if snap else m.best_ask
    spread = snap.spread if snap else m.spread
    bid_depth = snap.bid_depth_top5 if snap else None
    ask_depth = snap.ask_depth_top5 if snap else None
    seconds_to_close = (to_utc(m.end_time) - now).total_seconds() if m.end_time else None
    data_health = None
    if snap and snap.received_ts:
        age = (now - to_utc(snap.received_ts)).total_seconds()
        data_health = 1.0 if age <= settings.stale_after_seconds else 0.3
    return {
        "id": m.id, "slug": m.slug, "asset": m.asset_symbol, "window_minutes": m.window_minutes,
        "title": m.title, "status": m.status,
        "start_time": to_utc(m.start_time).isoformat() if m.start_time else None,
        "end_time": to_utc(m.end_time).isoformat() if m.end_time else None,
        "seconds_to_close": round(seconds_to_close, 1) if seconds_to_close is not None else None,
        "up_price": up_price, "down_price": (1 - up_price) if up_price is not None else None,
        "best_bid": best_bid, "best_ask": best_ask, "spread": spread,
        "bid_depth": bid_depth, "ask_depth": ask_depth, "data_health": data_health,
        "enable_order_book": m.enable_order_book, "parse_status": m.parse_status,
    }


def _universe_base():
    # Restrict to the configured 5m/15m universe, well-parsed markets with a real orderbook.
    return select(models.Market).where(
        models.Market.asset_symbol.in_([a.upper() for a in settings.assets]),
        models.Market.window_minutes.in_(settings.windows_minutes),
        models.Market.parse_status == "ok",
    )


def _rows_for(db: Session, markets: list[models.Market]) -> list[dict]:
    snaps = _latest_snapshots(db, [m.up_token_id for m in markets])
    return [market_row(db, m, snap=snaps.get(m.up_token_id), _prefetched=True) for m in markets]


@router.get("/markets/live")
def live_markets(db: Session = Depends(get_db)) -> dict:
    # Time-based ("live now"), so a market is never shown as live after it actually closes —
    # robust even if the stored status went stale between discovery passes.
    now = now_utc()
    markets = list(db.scalars(
        _universe_base()
        .where(models.Market.start_time <= now, models.Market.end_time > now)
        .order_by(models.Market.end_time.asc()).limit(LIVE_LIMIT)))
    return {"markets": _rows_for(db, markets)}


@router.get("/markets/upcoming")
def upcoming_markets(db: Session = Depends(get_db)) -> dict:
    now = now_utc()
    markets = list(db.scalars(
        _universe_base()
        .where(models.Market.start_time > now)
        .order_by(models.Market.start_time.asc()).limit(200)))
    return {"markets": _rows_for(db, markets)}


@router.get("/markets/{market_id}")
def market_detail(market_id: int, db: Session = Depends(get_db)) -> dict:
    m = db.get(models.Market, market_id)
    if not m:
        raise HTTPException(404, "market not found")
    outcomes = [{"outcome_index": o.outcome_index, "outcome_name": o.outcome_name,
                 "token_id": o.token_id, "last_price": o.last_price, "is_winner": o.is_winner}
                for o in sorted(m.outcomes_rel, key=lambda x: x.outcome_index)]
    market = {c.name: getattr(m, c.name) for c in m.__table__.columns}
    for k in ("start_time", "end_time", "last_updated", "created_at"):
        if market.get(k) is not None:
            market[k] = market[k].isoformat()
    market.pop("raw", None)
    return {"market": market, "outcomes": outcomes}


@router.get("/markets/{market_id}/replay")
def market_replay(market_id: int, fetch_live: bool = Query(True), db: Session = Depends(get_db)) -> dict:
    replay = build_replay(db, market_id, fetch_live=fetch_live)
    if replay is None:
        raise HTTPException(404, "market not found")
    return replay
