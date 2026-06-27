"""Forward paper-trading: latency-account fill/settlement + the engine's latency effect.

These are offline/deterministic — they drive the engine's pure tick methods with synthetic book
updates, no network. The headline test proves the whole point of the feature: with the SAME
decision, a higher-latency account fills at a worse price and ends with less PnL.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.fees import FeeSchedule
from app.paper.accounts import (
    Decision,
    LiveBook,
    account_summary,
    fill_order,
    make_orders,
    settle_order,
)
from app.paper.decide import LiveMarketState, decide_live
from app.paper.engine import MarketInfo, PaperConfig, PaperEngine

UTC = timezone.utc
ZERO_FEE = FeeSchedule(rate=0.0, present=True)


def _book(token, bid, ask, ts):
    return LiveBook(token_id=token, best_bid=bid, best_ask=ask, mid=(bid + ask) / 2,
                    bid_depth=500, ask_depth=500, ts=ts)


def _decision(outcome, ask, ts, size=100.0):
    return Decision(decision_id="d1", market_id=1, condition_id="0xc", asset="BTC",
                    window_minutes=5, outcome=outcome, token_id="UP",
                    decision_ts=ts, decision_book=_book("UP", ask - 0.01, ask, ts), size=size)


# --------------------------------------------------------------------- accounts


def test_fill_records_latency_slippage():
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    d = _decision("Up", 0.50, t0)
    o = make_orders(d, [250])[0]
    # book moved up (ask 0.50 -> 0.55) during the 250ms flight
    fill_order(o, _book("UP", 0.54, 0.55, t0 + timedelta(milliseconds=250)),
               schedule=ZERO_FEE, fee_scenario="none")
    assert o.status == "filled"
    assert o.fill_price == 0.55
    assert o.slippage_vs_decision == pytest.approx(0.05)   # paid 5c more due to latency


def test_fill_missed_when_no_liquidity():
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    o = make_orders(_decision("Up", 0.5, t0), [100])[0]
    fill_order(o, LiveBook("UP", None, None, None), schedule=ZERO_FEE, fee_scenario="none")
    assert o.status == "missed"
    assert o.reason == "no_liquidity_at_arrival"


def test_fill_rejected_on_adverse_move_when_tolerance_set():
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    o = make_orders(_decision("Up", 0.50, t0), [100])[0]
    fill_order(o, _book("UP", 0.69, 0.70, t0), schedule=ZERO_FEE, fee_scenario="none",
               max_slippage=0.05)  # 0.20 move > 0.05 tolerance
    assert o.status == "missed"
    assert o.reason == "adverse_move_exceeds_tolerance"


def test_settle_win_and_loss():
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    win = make_orders(_decision("Up", 0.40, t0), [0])[0]
    fill_order(win, _book("UP", 0.39, 0.40, t0), schedule=ZERO_FEE, fee_scenario="none")
    settle_order(win, "Up", t0 + timedelta(minutes=5))
    assert win.won is True
    assert win.pnl == pytest.approx(100 * (1 - 0.40))   # +60

    lose = make_orders(_decision("Up", 0.40, t0), [0])[0]
    fill_order(lose, _book("UP", 0.39, 0.40, t0), schedule=ZERO_FEE, fee_scenario="none")
    settle_order(lose, "Down", t0 + timedelta(minutes=5))
    assert lose.won is False
    assert lose.pnl == pytest.approx(-100 * 0.40)        # -40


# --------------------------------------------------------------------- decide


def test_decide_momentum_and_stale_odds():
    rng = random.Random(1)
    up = LiveMarketState(market_id=1, asset="BTC", window_minutes=5, elapsed_s=60,
                         up_book=None, down_book=None, up_mid_now=0.5, up_mid_prev=0.5,
                         spot_now=101.0, spot_prev=100.0)
    assert decide_live("momentum", up, {}, rng) == "Up"
    assert decide_live("mean_reversion", up, {}, rng) == "Down"
    # stale odds: spot moved +100bps but odds didn't move -> bet Up
    stale = LiveMarketState(market_id=1, asset="BTC", window_minutes=5, elapsed_s=60,
                            up_book=None, down_book=None, up_mid_now=0.50, up_mid_prev=0.50,
                            spot_now=101.0, spot_prev=100.0)
    assert decide_live("stale_odds", stale, {"spot_move_bps": 5}, rng) == "Up"
    # if odds already repriced, no trade
    repriced = LiveMarketState(market_id=1, asset="BTC", window_minutes=5, elapsed_s=60,
                               up_book=None, down_book=None, up_mid_now=0.60, up_mid_prev=0.50,
                               spot_now=101.0, spot_prev=100.0)
    assert decide_live("stale_odds", repriced, {"spot_move_bps": 5}, rng) is None


def test_decide_no_signal_on_flat():
    rng = random.Random(1)
    flat = LiveMarketState(market_id=1, asset="BTC", window_minutes=5, elapsed_s=60,
                           up_book=None, down_book=None, up_mid_now=0.5, up_mid_prev=0.5,
                           spot_now=100.0, spot_prev=100.0)
    assert decide_live("momentum", flat, {}, rng) is None  # no move => no bet


# --------------------------------------------------------------------- engine: THE latency effect


def test_engine_latency_effect_is_real():
    """Same decision, three latencies. The ask rises 0.50 -> 0.55 -> 0.60 during the flight, so
    the 0ms account fills at 0.50, 250ms at 0.55, 1000ms at 0.60 -> monotonically worse PnL."""
    cfg = PaperConfig(strategy_key="always_up", latency_grid_ms=[0, 250, 1000], size=100,
                      fee_scenario="none", entry_after_s=0.0, entry_before_close_s=0.0,
                      duration_s=None)
    eng = PaperEngine(cfg)
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    mi = MarketInfo(market_id=1, condition_id="0xc", asset="BTC", window_minutes=5,
                    start_time=t0 - timedelta(seconds=60), end_time=t0 + timedelta(seconds=60),
                    up_token="UP", down_token="DN", schedule=ZERO_FEE)
    eng.markets[1] = mi
    eng.token_to_market = {"UP": (1, "Up"), "DN": (1, "Down")}

    # book at decision: ask 0.50
    eng.on_book("UP", _book("UP", 0.49, 0.50, t0))
    decided = eng.decision_tick(now=t0)
    assert len(decided) == 1 and decided[0].outcome == "Up"
    assert len(eng.orders) == 3  # one per latency

    # book rises while orders are in flight
    eng.on_book("UP", _book("UP", 0.54, 0.55, t0 + timedelta(milliseconds=250)))
    eng.on_book("UP", _book("UP", 0.59, 0.60, t0 + timedelta(milliseconds=1000)))

    eng.fill_tick(now=t0 + timedelta(seconds=2))
    fills = {o.latency_ms: o.fill_price for o in eng.orders}
    assert fills[0] == pytest.approx(0.50)
    assert fills[250] == pytest.approx(0.55)
    assert fills[1000] == pytest.approx(0.60)

    # settle as a WIN -> lower fill price = higher PnL, so latency strictly erodes PnL
    eng.resolutions["0xc"] = "Up"
    eng.settle_tick(now=t0 + timedelta(minutes=5))
    pnl = {o.latency_ms: o.pnl for o in eng.orders}
    assert pnl[0] == pytest.approx(50.0)     # 100*(1-0.50)
    assert pnl[250] == pytest.approx(45.0)
    assert pnl[1000] == pytest.approx(40.0)
    assert pnl[0] > pnl[250] > pnl[1000]     # the whole point: latency costs money

    verdict = eng.latency_verdict()
    decay = verdict["pnl_decay_vs_zero_latency"]
    assert decay[250] == pytest.approx(-5.0)
    assert decay[1000] == pytest.approx(-10.0)


def test_engine_one_entry_per_market():
    cfg = PaperConfig(strategy_key="always_up", latency_grid_ms=[0], size=100,
                      entry_after_s=0.0, entry_before_close_s=0.0, duration_s=None)
    eng = PaperEngine(cfg)
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    eng.markets[1] = MarketInfo(1, "0xc", "BTC", 5, t0 - timedelta(seconds=30),
                                t0 + timedelta(seconds=60), "UP", "DN", ZERO_FEE)
    eng.token_to_market = {"UP": (1, "Up")}
    eng.on_book("UP", _book("UP", 0.49, 0.50, t0))
    assert len(eng.decision_tick(now=t0)) == 1
    assert len(eng.decision_tick(now=t0 + timedelta(seconds=3))) == 0  # already entered
