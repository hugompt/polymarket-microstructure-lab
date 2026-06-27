"""Strategy simulator: baselines, determinism, latency, fill models, missing-data handling."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.strategies.simulator import run_backtest


def _seed_markets(make_market, n=20, up_fraction=0.5):
    markets = []
    for i in range(n):
        resolved = "Up" if i < n * up_fraction else "Down"
        markets.append(make_market(asset="BTC", window=5, resolved=resolved, last_trade_price=0.5))
    return markets


def test_random_baseline_runs_and_is_deterministic(db, make_market):
    _seed_markets(make_market, 20)
    db.commit()
    r1 = run_backtest("random", assets=["BTC"], windows=[5], size=100, db=db,
                      persist=False, compare_random=False, seed=42)
    r2 = run_backtest("random", assets=["BTC"], windows=[5], size=100, db=db,
                      persist=False, compare_random=False, seed=42)
    assert r1["metrics"]["n_filled"] == 20
    assert r1["metrics"]["net_pnl"] == r2["metrics"]["net_pnl"]  # same seed => identical


def test_always_up_vs_always_down(db, make_market):
    _seed_markets(make_market, 20, up_fraction=0.75)  # 75% resolve Up
    db.commit()
    up = run_backtest("always_up", assets=["BTC"], windows=[5], size=100, db=db,
                      persist=False, compare_random=False)
    down = run_backtest("always_down", assets=["BTC"], windows=[5], size=100, db=db,
                        persist=False, compare_random=False)
    assert up["metrics"]["win_rate"] == pytest.approx(0.75)
    assert down["metrics"]["win_rate"] == pytest.approx(0.25)
    assert up["metrics"]["net_pnl"] > down["metrics"]["net_pnl"]


def test_vs_random_baseline_attached(db, make_market):
    _seed_markets(make_market, 40)
    db.commit()
    out = run_backtest("always_up", assets=["BTC"], windows=[5], size=100, db=db,
                       persist=False, compare_random=True)
    assert out["vs_random"] is not None
    assert out["metrics"]["vs_random_net_pnl"] is not None


def test_latency_does_not_crash_and_runs(db, make_market):
    _seed_markets(make_market, 10)
    db.commit()
    for latency in (0, 40, 100, 250, 500, 1000):
        out = run_backtest("always_up", assets=["BTC"], windows=[5], latency_ms=latency,
                           size=100, db=db, persist=False, compare_random=False)
        assert out["metrics"]["n_filled"] == 10


def test_missing_data_strategy_is_skipped_not_crashed(db, make_market):
    _seed_markets(make_market, 10)  # no ticks recorded
    db.commit()
    out = run_backtest("momentum_binance", assets=["BTC"], windows=[5], db=db,
                       persist=False, compare_random=False)
    assert out["metrics"]["n_filled"] == 0
    assert out["metrics"]["n_markets_acted"] == 0
    assert out["metrics"]["skipped"].get("binance_ticks") == 10
    assert out["metrics"]["is_low_sample"] is True
    assert any("statistically" in w or "Skipped" in w for w in out["warnings"])


def test_low_sample_warning(db, make_market):
    _seed_markets(make_market, 5)
    db.commit()
    out = run_backtest("always_up", assets=["BTC"], windows=[5], db=db,
                       persist=False, compare_random=False)
    assert out["metrics"]["is_low_sample"] is True
    assert any("statistically" in w.lower() for w in out["warnings"])


def test_maker_fill_can_miss(db, make_market, make_snapshot):
    """Post-only maker resting at the bid misses when the book never trades through it."""
    m = make_market(asset="BTC", window=5, resolved="Up")
    start = m.start_time
    # entry book: bid 0.40 / ask 0.50 ; later book keeps ask at 0.50 (never <= 0.40) -> miss
    make_snapshot(m.up_token_id, ts=start + timedelta(seconds=1), best_bid=0.40, best_ask=0.50)
    make_snapshot(m.up_token_id, ts=start + timedelta(seconds=120), best_bid=0.41, best_ask=0.50)
    db.commit()
    out = run_backtest("always_up", assets=["BTC"], windows=[5], fill_model="maker",
                       size=100, db=db, persist=False, compare_random=False)
    filled = [t for t in out["trades"] if t["filled"]]
    unfilled = [t for t in out["trades"] if not t["filled"]]
    assert len(unfilled) >= 1
    assert all(t["reason_unfilled"] == "missed_fill" for t in unfilled)


def test_taker_fills_from_book_high_fidelity(db, make_market, make_snapshot):
    m = make_market(asset="BTC", window=5, resolved="Up")
    make_snapshot(m.up_token_id, ts=m.start_time + timedelta(seconds=1),
                  best_bid=0.40, best_ask=0.45)
    db.commit()
    out = run_backtest("always_up", assets=["BTC"], windows=[5], fill_model="taker",
                       size=10, db=db, persist=False, compare_random=False)
    t = [x for x in out["trades"] if x["filled"]][0]
    assert t["raw"]["fidelity"] == "high"
    assert t["fill_price"] == pytest.approx(0.45, abs=0.02)  # crossed to ask (+ maybe slippage)


def test_book_as_of_is_strict_no_lookahead(db, make_market, make_snapshot):
    """Regression (audit #2): a signal must never see a FUTURE snapshot. book_as_of is strict
    (None when only a later snapshot exists); the lenient book_at fallback is fill-pricing only."""
    from app.strategies.simulator import build_context
    m = make_market(asset="BTC", window=5, resolved="Up")
    make_snapshot(m.up_token_id, ts=m.start_time + timedelta(seconds=200), best_bid=0.6, best_ask=0.62)
    db.commit()
    ctx = build_context(db, m, None)
    at = ctx._t(60)  # decision 60s in, before the only (200s) snapshot
    assert ctx.book_as_of(m.up_token_id, at) is None        # strict: no future leak
    assert ctx.book_at(m.up_token_id, at) is not None        # lenient fallback exists (fills only)


def test_buy_open_skips_without_book(db, make_market):
    """Regression (audit #2/#13): 'buy the favorite' strategies can't know the favorite without
    a book, so they SKIP (no arbitrary Up default / no lookahead) rather than fabricate trades."""
    for _ in range(5):
        make_market(asset="BTC", window=5, resolved="Up")  # no snapshots
    db.commit()
    out = run_backtest("buy_open", assets=["BTC"], windows=[5], db=db,
                       persist=False, compare_random=False)
    assert out["metrics"]["n_filled"] == 0
    assert out["metrics"]["skipped"].get("orderbook") == 5


def test_partial_fill_metrics_visible(db, make_market, make_snapshot):
    """Regression (audit #4): a depth-capped fill is flagged partial and notional_fill_rate < 1."""
    m = make_market(asset="BTC", window=5, resolved="Up")
    # ask depth (top5=400) far below the 100k order -> partial fill
    s = make_snapshot(m.up_token_id, ts=m.start_time + timedelta(seconds=1),
                      best_bid=0.40, best_ask=0.45)
    s.ask_depth_top5 = 400.0
    s.ask_depth_top10 = 400.0
    db.commit()
    out = run_backtest("always_up", assets=["BTC"], windows=[5], fill_model="taker",
                       size=100_000, db=db, persist=False, compare_random=False)
    assert out["metrics"]["n_partial_fills"] >= 1
    assert out["metrics"]["notional_fill_rate"] is not None
    assert out["metrics"]["notional_fill_rate"] < 1.0


def test_persist_creates_run_rows(db, make_market):
    _seed_markets(make_market, 10)
    db.commit()
    out = run_backtest("always_up", assets=["BTC"], windows=[5], db=db,
                       persist=True, compare_random=False)
    from app.db import models
    from sqlalchemy import select, func
    assert out["run_id"] is not None
    run = db.get(models.StrategyRun, out["run_id"])
    assert run.metrics is not None
    n_trades = db.scalar(select(func.count()).select_from(models.StrategyRunTrade)
                         .where(models.StrategyRunTrade.run_id == out["run_id"]))
    assert n_trades == 10
