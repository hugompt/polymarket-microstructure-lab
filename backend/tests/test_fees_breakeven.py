"""Fee model + dynamic break-even tests (rule 12: break-even is computed, never hardcoded)."""
from __future__ import annotations

import pytest

from app.analysis.fees import (
    CONSERVATIVE,
    MAKER_LIKE,
    NONE,
    TAKER_LIKE,
    FeeSchedule,
    breakeven_winrate,
    compute_fee_per_share,
    trade_economics,
)


def test_zero_fee_breakeven_equals_entry_price():
    sch = FeeSchedule(rate=0.0, present=True)
    for price in (0.1, 0.5, 0.9, 0.97):
        be = breakeven_winrate(price, sch, NONE)
        assert be == pytest.approx(price, abs=1e-9)


def test_breakeven_rises_with_fees():
    """With fees, break-even must exceed the naive (entry-price) break-even."""
    sch = FeeSchedule(rate=0.07, exponent=1, taker_only=True, rebate_rate=0.2, present=True)
    for price in (0.2, 0.5, 0.9):
        naive = price
        be = breakeven_winrate(price, sch, TAKER_LIKE)
        assert be >= naive
        assert be <= 1.0


def test_breakeven_at_097_is_about_097():
    """The headline skeptical fact: buying at $0.97 needs ~97 %+ win rate."""
    sch = FeeSchedule(rate=0.07, exponent=1, taker_only=True, rebate_rate=0.2, present=True)
    be = breakeven_winrate(0.97, sch, CONSERVATIVE)
    assert 0.97 <= be <= 0.99


def test_fee_proportional_to_min_side():
    """Fee uses min(p, 1-p): smaller near the extremes, largest at 0.5."""
    sch = FeeSchedule(rate=0.1, exponent=1, taker_only=True, present=True)
    f_mid = compute_fee_per_share(0.5, sch, TAKER_LIKE).fee_win
    f_edge = compute_fee_per_share(0.95, sch, TAKER_LIKE).fee_win
    assert f_mid > f_edge
    assert f_edge == pytest.approx(0.1 * 0.05, abs=1e-9)


def test_maker_taker_scenarios_differ():
    sch = FeeSchedule(rate=0.07, taker_only=True, rebate_rate=0.2, present=True)
    maker = compute_fee_per_share(0.5, sch, MAKER_LIKE)
    taker = compute_fee_per_share(0.5, sch, TAKER_LIKE)
    assert maker.fee_win == 0.0          # taker-only schedule => makers not charged
    assert taker.fee_win > 0.0


def test_missing_schedule_emits_warning():
    sch = FeeSchedule.from_market(None)
    assert sch.present is False
    fb = compute_fee_per_share(0.5, sch, TAKER_LIKE)
    assert any("fallback" in w or "missing" in w for w in fb.warnings)


def test_schedule_from_market_dict():
    sch = FeeSchedule.from_market({"feeSchedule": {"rate": 0.05, "exponent": 1,
                                                   "takerOnly": True, "rebateRate": 0.1}})
    assert sch.present is True
    assert sch.rate == 0.05


def test_ev_negative_when_winprob_equals_price():
    """If the true win prob equals the entry price (fair market), EV after fees is <= 0."""
    sch = FeeSchedule(rate=0.07, exponent=1, taker_only=True, present=True)
    econ = trade_economics(entry_price=0.97, size=30, schedule=sch,
                           scenario=TAKER_LIKE, win_prob=0.97, effective_entry_price=0.97)
    assert econ.ev_per_share is not None
    assert econ.ev_per_share <= 0  # only fees, no edge => non-positive


def test_taker_spread_cost_from_book():
    sch = FeeSchedule(rate=0.0, present=True)
    econ = trade_economics(entry_price=0.5, size=10, schedule=sch, scenario=TAKER_LIKE,
                           best_bid=0.49, best_ask=0.53)
    # taker crosses to the ask; effective entry = ask, spread cost vs mid (0.51) = 0.02/share
    assert econ.effective_entry_price == pytest.approx(0.53)
    assert econ.spread_cost == pytest.approx(0.02 * 10, abs=1e-6)
