"""Wallet-trade enrichment.

For each linked wallet trade, attach microstructure context:
  * nearest orderbook snapshot before & after (for this outcome token)
  * nearest Binance & Chainlink price ticks before & after (for the asset)
  * seconds since open / until close, market phase (open / mid / close)
  * entry price bucket, spread & depth at entry
  * dynamically-computed break-even win rate and a "fair-market" EV per share

Nearest lookups go straight to the DB with indexed range queries (max ts <= t, min ts > t),
so this scales to large trade histories.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.fees import FeeSchedule, breakeven_winrate, get_scenario, trade_economics
from ..db import models
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..util.normalize import price_bucket

log = get_logger("services.enrichment")

OPEN_FRACTION = 0.2
MIN_PHASE_SECONDS = 60.0


def _phase(seconds_since_open: float | None, seconds_until_close: float | None,
           window_minutes: int | None) -> str | None:
    if seconds_since_open is None or seconds_until_close is None:
        return None
    edge = MIN_PHASE_SECONDS
    if window_minutes:
        edge = max(MIN_PHASE_SECONDS, window_minutes * 60 * OPEN_FRACTION)
    if seconds_since_open <= edge:
        return "open"
    if seconds_until_close <= edge:
        return "close"
    return "mid"


def _nearest_book(db: Session, token_id: str, ts, before: bool):
    stmt = select(models.OrderbookSnapshot).where(
        models.OrderbookSnapshot.token_id == token_id,
        models.OrderbookSnapshot.accepted.is_(True),
    )
    if before:
        stmt = stmt.where(models.OrderbookSnapshot.received_ts <= ts).order_by(
            models.OrderbookSnapshot.received_ts.desc())
    else:
        stmt = stmt.where(models.OrderbookSnapshot.received_ts > ts).order_by(
            models.OrderbookSnapshot.received_ts.asc())
    return db.scalars(stmt.limit(1)).first()


def _nearest_tick(db: Session, asset: str, source: str, ts, before: bool):
    col = models.CryptoPriceTick.received_ts
    stmt = select(models.CryptoPriceTick).where(
        models.CryptoPriceTick.asset_symbol == asset,
        models.CryptoPriceTick.source == source,
        models.CryptoPriceTick.accepted.is_(True),
    )
    if before:
        stmt = stmt.where(col <= ts).order_by(col.desc())
    else:
        stmt = stmt.where(col > ts).order_by(col.asc())
    return db.scalars(stmt.limit(1)).first()


def enrich_trade(db: Session, trade: models.Trade, scenario: str = "conservative") -> models.WalletTradeEnrichment | None:
    if trade.ts_utc is None:
        return None
    market = db.get(models.Market, trade.market_id) if trade.market_id else None

    seconds_since_open = seconds_until_close = None
    window = market.window_minutes if market else None
    if market and market.start_time and trade.ts_utc:
        seconds_since_open = (trade.ts_utc - market.start_time).total_seconds()
    if market and market.end_time and trade.ts_utc:
        seconds_until_close = (market.end_time - trade.ts_utc).total_seconds()

    book_before = _nearest_book(db, trade.asset, trade.ts_utc, True) if trade.asset else None
    book_after = _nearest_book(db, trade.asset, trade.ts_utc, False) if trade.asset else None

    asset_sym = market.asset_symbol if market else None
    binance_b = _nearest_tick(db, asset_sym, "binance", trade.ts_utc, True) if asset_sym else None
    binance_a = _nearest_tick(db, asset_sym, "binance", trade.ts_utc, False) if asset_sym else None
    chain_b = _nearest_tick(db, asset_sym, "chainlink", trade.ts_utc, True) if asset_sym else None
    chain_a = _nearest_tick(db, asset_sym, "chainlink", trade.ts_utc, False) if asset_sym else None

    schedule = FeeSchedule.from_market(market)
    sc = get_scenario(scenario)
    entry = trade.price if trade.price is not None else 0.5
    be = breakeven_winrate(entry, schedule, sc)
    econ = trade_economics(
        entry_price=entry, size=trade.size or 1.0, schedule=schedule, scenario=sc,
        win_prob=entry,  # fair-market assumption: implied prob == price
        best_bid=book_before.best_bid if book_before else None,
        best_ask=book_before.best_ask if book_before else None,
        effective_entry_price=entry,
    )

    enr = trade.enrichment or models.WalletTradeEnrichment(trade_id=trade.id)
    enr.market_id = trade.market_id
    enr.asset_symbol = asset_sym
    enr.window_minutes = window
    enr.seconds_since_open = seconds_since_open
    enr.seconds_until_close = seconds_until_close
    enr.market_phase = _phase(seconds_since_open, seconds_until_close, window)
    enr.entry_price_bucket = price_bucket(trade.price)
    enr.spread_at_entry = book_before.spread if book_before else None
    enr.depth_at_entry = (book_before.bid_depth_top5 or 0) + (book_before.ask_depth_top5 or 0) if book_before else None
    enr.nearest_book_before_id = book_before.id if book_before else None
    enr.nearest_book_after_id = book_after.id if book_after else None
    enr.binance_before_price = binance_b.price if binance_b else None
    enr.binance_after_price = binance_a.price if binance_a else None
    enr.chainlink_before_price = chain_b.price if chain_b else None
    enr.chainlink_after_price = chain_a.price if chain_a else None
    enr.breakeven_winrate = be
    enr.ev_per_share = econ.ev_per_share
    enr.notes = {
        "scenario": scenario,
        "fee_schedule_present": schedule.present,
        "naive_breakeven": econ.naive_breakeven,
        "fee_win_per_share": econ.fee_win_per_share,
    }
    if enr.id is None:
        db.add(enr)
    return enr


def relink_trades(db: Session, wallet_address: str | None = None) -> int:
    """Backfill market_id on trades whose market was discovered after the trade was synced."""
    stmt = select(models.Trade).where(models.Trade.market_id.is_(None),
                                      models.Trade.condition_id.is_not(None))
    if wallet_address:
        stmt = stmt.where(models.Trade.wallet_address == wallet_address.lower())
    linked = 0
    cond_cache: dict[str, int | None] = {}
    for t in db.scalars(stmt):
        if t.condition_id not in cond_cache:
            cond_cache[t.condition_id] = db.scalar(
                select(models.Market.id).where(models.Market.condition_id == t.condition_id))
        mid = cond_cache[t.condition_id]
        if mid:
            t.market_id = mid
            linked += 1
    return linked


def enrich_wallet(wallet_address: str, *, scenario: str = "conservative",
                  db: Session | None = None, only_missing: bool = True) -> dict:
    addr = wallet_address.lower()

    def _run(s: Session) -> dict:
        relinked = relink_trades(s, addr)
        stmt = select(models.Trade).where(models.Trade.wallet_address == addr)
        if only_missing:
            stmt = stmt.where(~models.Trade.enrichment.has())
        trades = list(s.scalars(stmt))
        enriched = 0
        for t in trades:
            if enrich_trade(s, t, scenario=scenario) is not None:
                enriched += 1
        return {"relinked": relinked, "enriched": enriched, "considered": len(trades)}

    if db is not None:
        out = _run(db)
        db.commit()
        return out
    with session_scope() as s:
        return _run(s)
