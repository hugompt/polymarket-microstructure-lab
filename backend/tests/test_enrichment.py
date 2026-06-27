"""Trade enrichment: nearest book/tick before-after, market phase, entry bucket, break-even."""
from __future__ import annotations

from datetime import timedelta

from app.services.enrichment import enrich_trade


def test_enrichment_nearest_and_phase(db, make_market, make_trade, make_snapshot, make_tick):
    m = make_market(asset="BTC", window=5, resolved="Up")
    start = m.start_time
    # trade 30s into a 5-min window -> "open" phase (edge = max(60, 0.2*300)=60s)
    trade = make_trade(m, side="BUY", outcome="Up", price=0.40, size=100,
                       ts=start + timedelta(seconds=30))
    up_tok = m.up_token_id
    # snapshots around the trade time
    before = make_snapshot(up_tok, ts=start + timedelta(seconds=20), best_bid=0.39, best_ask=0.41)
    after = make_snapshot(up_tok, ts=start + timedelta(seconds=45), best_bid=0.42, best_ask=0.44)
    # ticks
    make_tick("BTC", ts=start + timedelta(seconds=25), price=60000.0, source="binance")
    make_tick("BTC", ts=start + timedelta(seconds=40), price=60050.0, source="binance")
    make_tick("BTC", ts=start + timedelta(seconds=10), price=59990.0, source="chainlink")

    enr = enrich_trade(db, trade)
    db.commit()
    assert enr is not None
    assert enr.nearest_book_before_id == before.id
    assert enr.nearest_book_after_id == after.id
    assert enr.market_phase == "open"
    assert enr.entry_price_bucket == "35-50"
    assert enr.seconds_since_open == 30.0
    assert enr.seconds_until_close == 270.0
    assert enr.spread_at_entry is not None
    assert enr.binance_before_price == 60000.0
    assert enr.binance_after_price == 60050.0
    assert enr.chainlink_before_price == 59990.0
    # break-even computed dynamically and > naive entry due to fees
    assert enr.breakeven_winrate >= 0.40


def test_enrichment_close_phase(db, make_market, make_trade):
    m = make_market(asset="ETH", window=5, resolved="Down")
    trade = make_trade(m, outcome="Down", price=0.95,
                       ts=m.start_time + timedelta(seconds=270))  # last 30s
    enr = enrich_trade(db, trade)
    db.commit()
    assert enr.market_phase == "close"
    assert enr.entry_price_bucket == "95-100"


def test_enrichment_handles_missing_microstructure(db, make_market, make_trade):
    """No snapshots/ticks present -> enrichment still works, just with None context."""
    m = make_market(asset="SOL", window=15, resolved="Up")
    trade = make_trade(m, outcome="Up", price=0.5, ts=m.start_time + timedelta(seconds=400))
    enr = enrich_trade(db, trade)
    db.commit()
    assert enr is not None
    assert enr.nearest_book_before_id is None
    assert enr.binance_before_price is None
    assert enr.market_phase == "mid"
