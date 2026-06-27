"""Forward paper-trading API (read + bounded launch). Still SIMULATION — no real orders."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import models
from ...db.session import get_db
from ...paper.decide import LIVE_STRATEGIES, LIVE_STRATEGY_KEYS
from ...paper.engine import DEFAULT_LATENCY_GRID, PaperConfig, PaperEngine

router = APIRouter(tags=["paper"])

MAX_DURATION_S = 7200  # hard cap so an API-launched session can never run away
_RUNNING: dict[int, tuple] = {}   # session_id -> (engine, task)


class PaperStartRequest(BaseModel):
    strategy: str = "stale_odds"
    assets: list[str] | None = None
    windows: list[int] | None = None
    latencies_ms: list[int] = Field(default_factory=lambda: list(DEFAULT_LATENCY_GRID))
    size: float = 100.0
    duration_s: float = 900.0
    fee_scenario: str = "conservative"
    lookback_s: float = 20.0
    params: dict = Field(default_factory=dict)


@router.get("/paper/strategies")
def paper_strategies() -> dict:
    return {"strategies": LIVE_STRATEGIES}


def _account_rows(db: Session, session_id: int) -> list[dict]:
    """Aggregate paper_orders by latency for one session (works for CLI- or API-run sessions)."""
    orders = db.scalars(select(models.PaperOrder)
                        .where(models.PaperOrder.session_id == session_id)).all()
    by_lat: dict[int, list] = {}
    for o in orders:
        by_lat.setdefault(o.latency_ms, []).append(o)
    rows = []
    for lat in sorted(by_lat):
        mine = by_lat[lat]
        filled = [o for o in mine if o.status in ("filled", "settled")]
        settled = [o for o in mine if o.status == "settled"]
        missed = [o for o in mine if o.status == "missed"]
        wins = [o for o in settled if o.won]
        pnls = [o.pnl for o in settled if o.pnl is not None]
        slips = [o.slippage_vs_decision for o in mine if o.slippage_vs_decision is not None]
        rows.append({
            "latency_ms": lat, "n_decisions": len(mine), "n_filled": len(filled),
            "n_missed": len(missed), "n_settled": len(settled), "n_won": len(wins),
            "win_rate": round(len(wins) / len(settled), 4) if settled else None,
            "realized_pnl": round(sum(pnls), 4) if pnls else 0.0,
            "fees_paid": round(sum(o.fees or 0 for o in settled), 4),
            "avg_slippage_vs_decision": round(sum(slips) / len(slips), 6) if slips else 0.0,
            "fill_rate": round(len(filled) / len(mine), 4) if mine else None,
        })
    return rows


@router.get("/paper/sessions")
def paper_sessions(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    out = []
    for s in db.scalars(select(models.PaperSession)
                        .order_by(models.PaperSession.created_at.desc()).limit(limit)):
        rows = _account_rows(db, s.id)
        best = max(rows, key=lambda r: r["realized_pnl"]) if rows else None
        out.append({
            "id": s.id, "strategy_key": s.strategy_key, "status": s.status,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
            "assets": s.assets, "windows": s.windows, "latency_grid_ms": s.latency_grid_ms,
            "size": s.size, "is_running": s.id in _RUNNING,
            "best_latency_ms": best["latency_ms"] if best else None,
            "best_realized_pnl": best["realized_pnl"] if best else None,
        })
    return {"sessions": out}


@router.get("/paper/sessions/{session_id}")
def paper_session_detail(session_id: int, db: Session = Depends(get_db)) -> dict:
    s = db.get(models.PaperSession, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    rows = _account_rows(db, session_id)
    base = next((r["realized_pnl"] for r in rows if r["latency_ms"] == 0), None)
    if base is None and rows:
        base = rows[0]["realized_pnl"]
    decay = {r["latency_ms"]: round(r["realized_pnl"] - base, 4) for r in rows} if base is not None else {}
    # equity curve per latency
    equity = {}
    for e in db.scalars(select(models.PaperAccountEquity)
                        .where(models.PaperAccountEquity.session_id == session_id)
                        .order_by(models.PaperAccountEquity.ts.asc())):
        equity.setdefault(e.latency_ms, []).append(
            {"t": e.ts.isoformat() if e.ts else None, "realized_pnl": e.realized_pnl,
             "n_settled": e.n_settled})
    total_settled = sum(r["n_settled"] for r in rows)
    warnings = []
    if total_settled < max(1, len(rows)) * 30:
        warnings.append("Low sample: too few markets have resolved for a statistically meaningful "
                        "latency verdict. Run the session longer.")
    return {
        "session": {"id": s.id, "strategy_key": s.strategy_key, "status": s.status,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
                    "assets": s.assets, "windows": s.windows, "size": s.size,
                    "latency_grid_ms": s.latency_grid_ms, "fee_scenario": s.fee_scenario,
                    "is_running": session_id in _RUNNING, "config": s.config},
        "by_latency": rows,
        "pnl_decay_vs_zero_latency": decay,
        "equity_by_latency": equity,
        "warnings": warnings,
    }


@router.get("/paper/sessions/{session_id}/orders")
def paper_session_orders(session_id: int, limit: int = 1000, db: Session = Depends(get_db)) -> dict:
    rows = []
    for o in db.scalars(select(models.PaperOrder)
                        .where(models.PaperOrder.session_id == session_id)
                        .order_by(models.PaperOrder.decision_ts.desc()).limit(limit)):
        rows.append({
            "decision_id": o.decision_id, "latency_ms": o.latency_ms, "asset": o.asset_symbol,
            "window_minutes": o.window_minutes, "outcome": o.outcome,
            "decision_ts": o.decision_ts.isoformat() if o.decision_ts else None,
            "decision_price": o.decision_price, "fill_price": o.fill_price,
            "slippage_vs_decision": o.slippage_vs_decision, "status": o.status,
            "resolved_outcome": o.resolved_outcome, "won": o.won, "pnl": o.pnl, "fees": o.fees,
        })
    return {"orders": rows}


@router.post("/paper/start")
async def paper_start(req: PaperStartRequest) -> dict:
    if req.strategy not in LIVE_STRATEGY_KEYS:
        raise HTTPException(400, f"unknown live strategy '{req.strategy}'; "
                                 f"choose from {sorted(LIVE_STRATEGY_KEYS)}")
    cfg = PaperConfig(
        strategy_key=req.strategy, assets=req.assets, windows=req.windows,
        latency_grid_ms=req.latencies_ms, size=req.size, fee_scenario=req.fee_scenario,
        duration_s=min(req.duration_s, MAX_DURATION_S), lookback_s=req.lookback_s,
        params=req.params,
    )
    # PaperConfig defaults assets/windows from settings when None; honor that.
    if req.assets:
        cfg.assets = req.assets
    if req.windows:
        cfg.windows = req.windows
    engine = PaperEngine(cfg)
    sid = engine._start_session()

    async def _runner():
        try:
            await engine.run()
        finally:
            _RUNNING.pop(sid, None)

    task = asyncio.create_task(_runner())
    _RUNNING[sid] = (engine, task)
    return {"session_id": sid, "status": "running",
            "note": "SIMULATION only; no real orders. Capped at "
                    f"{int(min(req.duration_s, MAX_DURATION_S))}s."}


@router.post("/paper/sessions/{session_id}/stop")
async def paper_stop(session_id: int) -> dict:
    entry = _RUNNING.get(session_id)
    if not entry:
        raise HTTPException(404, "no running session with that id")
    engine, _task = entry
    engine.stop.set()
    return {"session_id": session_id, "status": "stopping"}
