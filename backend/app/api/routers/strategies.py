from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import models
from ...db.session import get_db
from ...strategies.registry import list_strategies
from ...strategies.simulator import run_backtest
from ...util.timeutil import parse_any_time

router = APIRouter(tags=["strategies"])


class RunRequest(BaseModel):
    strategy: str
    assets: list[str] | None = None
    windows: list[int] | None = None
    date_from: str | None = None
    date_to: str | None = None
    latency_ms: int = 100
    fill_model: str = "realistic"
    fee_scenario: str = "conservative"
    size: float = 100.0
    seed: int = 1234
    params: dict = Field(default_factory=dict)
    compare_random: bool = True


@router.get("/strategies/list")
def strategies_list() -> dict:
    return {"strategies": list_strategies()}


@router.post("/strategies/run")
def strategies_run(req: RunRequest, db: Session = Depends(get_db)) -> dict:
    try:
        out = run_backtest(
            req.strategy, assets=req.assets, windows=req.windows,
            date_from=parse_any_time(req.date_from), date_to=parse_any_time(req.date_to),
            latency_ms=req.latency_ms, fill_model=req.fill_model, fee_scenario=req.fee_scenario,
            size=req.size, params=req.params, compare_random=req.compare_random,
            persist=True, db=db, seed=req.seed,
        )
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    return {"run_id": out.get("run_id"), "strategy_key": out["strategy_key"],
            "metrics": out["metrics"], "vs_random": out["vs_random"], "warnings": out["warnings"]}


@router.get("/strategies/runs")
def strategies_runs(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    runs = []
    for r in db.scalars(select(models.StrategyRun)
                        .order_by(models.StrategyRun.created_at.desc()).limit(limit)):
        m = r.metrics
        runs.append({
            "id": r.id, "strategy_key": r.strategy_key, "label": r.label,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "fill_model": r.fill_model, "fee_scenario": r.fee_scenario, "latency_ms": r.latency_ms,
            "net_pnl": m.net_pnl if m else None, "win_rate": m.win_rate if m else None,
            "n_filled": m.n_filled if m else None,
            "vs_random_net_pnl": m.vs_random_net_pnl if m else None,
            "sample_warning": m.sample_warning if m else None,
        })
    return {"runs": runs}


@router.get("/strategies/runs/{run_id}")
def strategy_run_detail(run_id: int, include_trades: bool = True,
                        db: Session = Depends(get_db)) -> dict:
    r = db.get(models.StrategyRun, run_id)
    if not r:
        raise HTTPException(404, "run not found")
    m = r.metrics
    run = {"id": r.id, "strategy_key": r.strategy_key, "label": r.label, "params": r.params,
           "assets": r.assets, "windows": r.windows, "fill_model": r.fill_model,
           "fee_scenario": r.fee_scenario, "latency_ms": r.latency_ms,
           "created_at": r.created_at.isoformat() if r.created_at else None,
           "n_markets": r.n_markets, "n_attempts": r.n_attempts, "n_filled": r.n_filled}
    metrics = m.full if m else None
    trades = []
    if include_trades:
        for t in db.scalars(select(models.StrategyRunTrade)
                            .where(models.StrategyRunTrade.run_id == run_id).limit(2000)):
            trades.append({
                "intended_ts": t.intended_ts.isoformat() if t.intended_ts else None,
                "asset_symbol": t.asset_symbol, "window_minutes": t.window_minutes,
                "outcome_chosen": t.outcome_chosen, "filled": t.filled, "fill_price": t.fill_price,
                "size": t.size, "fees": t.fees, "won": t.won, "pnl": t.pnl,
                "entry_price_bucket": t.entry_price_bucket, "reason_unfilled": t.reason_unfilled})
    return {"run": run, "metrics": metrics,
            "vs_random": (m.full.get("vs_random") if m and m.full else None), "trades": trades}
