"""CSV exporters (stdlib csv; no pandas). Used by CLI `export` and the API export routes."""
from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import models
from .replay import build_replay


def _csv(rows: list[dict], fieldnames: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def wallet_trades_csv(db: Session, wallet: str) -> str:
    wallet = wallet.lower()
    rows = []
    for t in db.scalars(select(models.Trade).where(models.Trade.wallet_address == wallet)
                        .order_by(models.Trade.ts_utc.asc())):
        enr = t.enrichment
        rows.append({
            "ts_utc": t.ts_utc.isoformat() if t.ts_utc else None,
            "timestamp_epoch": t.timestamp_epoch, "asset": t.asset, "slug": t.slug,
            "condition_id": t.condition_id, "side": t.side, "outcome": t.outcome,
            "price": t.price, "size": t.size, "notional": t.notional,
            "transaction_hash": t.transaction_hash,
            "market_phase": enr.market_phase if enr else None,
            "seconds_until_close": enr.seconds_until_close if enr else None,
            "entry_price_bucket": enr.entry_price_bucket if enr else None,
            "breakeven_winrate": enr.breakeven_winrate if enr else None,
            "spread_at_entry": enr.spread_at_entry if enr else None,
        })
    return _csv(rows, ["ts_utc", "timestamp_epoch", "asset", "slug", "condition_id", "side",
                       "outcome", "price", "size", "notional", "transaction_hash", "market_phase",
                       "seconds_until_close", "entry_price_bucket", "breakeven_winrate",
                       "spread_at_entry"])


def market_replay_csv(db: Session, market_ref: str | int) -> str:
    replay = build_replay(db, market_ref, fetch_live=True)
    if replay is None:
        return "error\nmarket not found\n"
    rows = []
    for p in replay["series"]["price"]:
        rows.append({"t": p["t"], "kind": "price", "up": p.get("up"), "down": p.get("down")})
    for b in replay["series"]["book"]:
        rows.append({"t": b["t"], "kind": "book", "bid": b.get("bid"), "ask": b.get("ask"),
                     "spread": b.get("spread"), "mid": b.get("mid")})
    for s in ("binance", "chainlink"):
        for pt in replay["series"][s]:
            rows.append({"t": pt["t"], "kind": s, "spot": pt.get("p")})
    for w in replay["wallet_trades"]:
        rows.append({"t": w["t"], "kind": "wallet_trade", "side": w["side"],
                     "outcome": w["outcome"], "price": w["price"], "size": w["size"]})
    rows.sort(key=lambda r: (r["t"] or ""))
    return _csv(rows, ["t", "kind", "up", "down", "bid", "ask", "mid", "spread", "spot",
                       "side", "outcome", "price", "size"])


def strategy_run_csv(db: Session, run_id: int) -> str:
    rows = []
    for t in db.scalars(select(models.StrategyRunTrade).where(
            models.StrategyRunTrade.run_id == run_id)
            .order_by(models.StrategyRunTrade.intended_ts.asc())):
        rows.append({
            "intended_ts": t.intended_ts.isoformat() if t.intended_ts else None,
            "asset_symbol": t.asset_symbol, "window_minutes": t.window_minutes,
            "outcome_chosen": t.outcome_chosen, "filled": t.filled, "fill_price": t.fill_price,
            "size": t.size, "fees": t.fees, "slippage": t.slippage, "spread_cost": t.spread_cost,
            "resolved_outcome": t.resolved_outcome, "won": t.won, "pnl": t.pnl,
            "entry_price_bucket": t.entry_price_bucket, "reason_unfilled": t.reason_unfilled,
        })
    return _csv(rows, ["intended_ts", "asset_symbol", "window_minutes", "outcome_chosen", "filled",
                       "fill_price", "size", "fees", "slippage", "spread_cost", "resolved_outcome",
                       "won", "pnl", "entry_price_bucket", "reason_unfilled"])
