"""Independent wallet PnL reconstruction — known-answer + accounting separation."""
from __future__ import annotations

import pytest

from app.analysis.wallet import analyze_wallet


def test_reconstruction_known_answer(db, make_market, make_trade):
    # Market A resolves Up; wallet BUYs Up @0.40 size100 -> WIN (+0.60/sh gross)
    a = make_market(asset="BTC", resolved="Up")
    make_trade(a, side="BUY", outcome="Up", price=0.40, size=100, wallet="0xt")
    # Market B resolves Down; wallet BUYs Up @0.60 size100 -> LOSS (-0.60/sh)
    b = make_market(asset="BTC", resolved="Down")
    make_trade(b, side="BUY", outcome="Up", price=0.60, size=100, wallet="0xt")
    db.commit()

    res = analyze_wallet(db, "0xt", scenario="conservative")
    acc, stats, cov = res["accounting"], res["stats"], res["coverage"]

    # Win 60 - Loss 60 = 0 gross (both per-trade and market-level cash-flow).
    assert acc["reconstructed_pnl"] == pytest.approx(0.0, abs=1e-6)
    assert acc["reconstructed_market_level"] == pytest.approx(0.0, abs=1e-6)
    # fee on the winning side: 0.07 * min(0.4,0.6) * 100 = 2.8 (conservative)
    assert acc["estimated_fees"] == pytest.approx(2.8, abs=1e-3)
    assert acc["estimated_pnl_after_fees"] == pytest.approx(-2.8, abs=1e-3)
    assert stats["win_rate"] == 0.5
    assert acc["total_volume"] == pytest.approx(100.0)  # 0.4*100 + 0.6*100
    assert acc["portfolio_value"] == 0.0
    assert cov["resolution_coverage_pct"] == 100.0


def test_accounting_fields_are_separate(db, make_market, make_trade):
    m = make_market(resolved="Up")
    make_trade(m, outcome="Up", price=0.5, size=10, wallet="0xt")
    db.commit()
    acc = analyze_wallet(db, "0xt")["accounting"]
    # These are explicitly different concepts and must all be present & distinct keys.
    for k in ("reported_realized_pnl", "reconstructed_pnl", "estimated_pnl_after_fees",
              "portfolio_value", "total_volume"):
        assert k in acc
    assert "NOT profit" in " ".join(analyze_wallet(db, "0xt")["skeptic_notes"]) or \
           any("Portfolio value" in n for n in analyze_wallet(db, "0xt")["skeptic_notes"])


def test_unresolved_market_excluded_from_coverage(db, make_market, make_trade):
    resolved = make_market(resolved="Up")
    make_trade(resolved, outcome="Up", price=0.5, size=10, wallet="0xt")
    live = make_market(resolved=None, status="live")
    make_trade(live, outcome="Up", price=0.5, size=10, wallet="0xt")
    db.commit()
    cov = analyze_wallet(db, "0xt")["coverage"]
    assert cov["n_trades"] == 2
    assert cov["n_resolved_buy_trades"] == 1
    assert cov["resolution_coverage_pct"] == 50.0


def test_skeptic_notes_reference_unverified_claim(db, make_market, make_trade):
    m = make_market(resolved="Up")
    make_trade(m, outcome="Up", price=0.5, size=10, wallet="0xt")
    db.commit()
    notes = " ".join(analyze_wallet(db, "0xt")["skeptic_notes"])
    assert "UNVERIFIED" in notes
    assert "21k" in notes or "$21" in notes


def test_breakeven_by_bucket_present(db, make_market, make_trade):
    for i in range(5):
        m = make_market(resolved="Up")
        make_trade(m, outcome="Up", price=0.9, size=10, wallet="0xt")
    db.commit()
    bd = analyze_wallet(db, "0xt")["breakdowns"]
    assert "breakeven_by_bucket" in bd
    bucket = next((b for b in bd["breakeven_by_bucket"] if b["bucket"] == "85-95"), None)
    assert bucket is not None
    assert bucket["breakeven_winrate"] is not None  # dynamically computed
