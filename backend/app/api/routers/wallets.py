from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...analysis.wallet import analyze_wallet
from ...config import settings
from ...db import models
from ...db.session import get_db

router = APIRouter(tags=["wallets"])


@router.get("/wallets")
def list_wallets(db: Session = Depends(get_db)) -> dict:
    out = []
    for w in db.scalars(select(models.Wallet)):
        n = db.scalar(select(func.count()).select_from(models.Trade)
                      .where(models.Trade.wallet_address == w.address)) or 0
        out.append({"address": w.address, "label": w.label, "is_target": w.is_target,
                    "last_synced_at": w.last_synced_at.isoformat() if w.last_synced_at else None,
                    "n_trades": n})
    if settings.target_wallet and not any(w["address"] == settings.target_wallet.lower() for w in out):
        out.insert(0, {"address": settings.target_wallet.lower(), "label": settings.target_profile,
                       "is_target": True, "last_synced_at": None, "n_trades": 0})
    return {"wallets": out}


def _full(db: Session, address: str, scenario: str) -> dict:
    return analyze_wallet(db, address, scenario=scenario)


@router.get("/wallets/{address}/summary")
def wallet_summary(address: str, scenario: str = Query("conservative"),
                   db: Session = Depends(get_db)) -> dict:
    a = _full(db, address, scenario)
    acc = a["accounting"]
    return {
        "address": a["address"], "profile": a["profile"],
        "accounting": {
            "reported_realized_pnl": acc["reported_realized_pnl"],
            "reported_source": acc["reported_source"],
            "reconstructed_pnl": acc["reconstructed_pnl"],
            "estimated_pnl_after_fees": acc["estimated_pnl_after_fees"],
            "estimated_fees": acc["estimated_fees"],
            "portfolio_value": acc["portfolio_value"],
            "total_volume": acc["total_volume"], "rewards": acc["rewards"],
        },
        "stats": a["stats"], "coverage": a["coverage"],
        "warnings": a["warnings"], "skeptic_notes": a["skeptic_notes"],
    }


@router.get("/wallets/{address}/trades")
def wallet_trades(address: str, limit: int = Query(200, le=2000), offset: int = 0,
                  db: Session = Depends(get_db)) -> dict:
    addr = address.lower()
    total = db.scalar(select(func.count()).select_from(models.Trade)
                      .where(models.Trade.wallet_address == addr)) or 0
    rows = []
    for t in db.scalars(select(models.Trade).where(models.Trade.wallet_address == addr)
                        .order_by(models.Trade.ts_utc.desc()).limit(limit).offset(offset)):
        enr = t.enrichment
        rows.append({
            "ts_utc": t.ts_utc.isoformat() if t.ts_utc else None, "asset": t.asset,
            "slug": t.slug, "side": t.side, "outcome": t.outcome, "price": t.price,
            "size": t.size, "notional": t.notional, "transaction_hash": t.transaction_hash,
            "market_phase": enr.market_phase if enr else None,
            "seconds_until_close": enr.seconds_until_close if enr else None,
            "entry_price_bucket": enr.entry_price_bucket if enr else None,
            "breakeven_winrate": enr.breakeven_winrate if enr else None,
        })
    return {"total": total, "trades": rows}


@router.get("/wallets/{address}/pnl")
def wallet_pnl(address: str, scenario: str = Query("conservative"),
               db: Session = Depends(get_db)) -> dict:
    a = _full(db, address, scenario)
    by_day = a["by_day"]
    # Headline equity curve = the realistic AFTER-FEE cumulative; gross kept alongside.
    cumulative = [{"t": d["day"], "pnl": d["cumulative_pnl_after_fees"],
                   "pnl_gross": d["cumulative_pnl"]} for d in by_day]
    return {"by_day": by_day, "cumulative": cumulative,
            "reported_vs_reconstructed": {
                "reported": a["accounting"]["reported_realized_pnl"],
                "reconstructed": a["accounting"]["reconstructed_pnl"],
                "estimated_after_fees": a["accounting"]["estimated_pnl_after_fees"]}}


@router.get("/wallets/{address}/breakdowns")
def wallet_breakdowns(address: str, scenario: str = Query("conservative"),
                      db: Session = Depends(get_db)) -> dict:
    a = _full(db, address, scenario)
    return a["breakdowns"]
