"""Data-quality engine: stale / duplicate / out-of-order / impossible-jump detection."""
from __future__ import annotations

from datetime import timedelta

from app.services.data_quality import FeedTracker
from app.util.timeutil import now_utc


def _epoch(dt):
    return dt.timestamp()


def test_first_tick_accepted():
    tr = FeedTracker(source="binance", key="BTC", asset_symbol="BTC")
    now = now_utc()
    res = tr.assess(value=60000.0, ts_epoch=_epoch(now), received_at=now)
    assert res.accepted
    assert not res.flagged


def test_duplicate_value_ts_rejected():
    tr = FeedTracker(source="binance", key="BTC")
    now = now_utc()
    tr.assess(value=60000.0, ts_epoch=100.0, received_at=now)
    res = tr.assess(value=60000.0, ts_epoch=100.0, received_at=now)
    assert res.is_duplicate
    assert not res.accepted
    assert tr.duplicates == 1


def test_duplicate_hash_rejected():
    tr = FeedTracker(source="clob_ws", key="TOK")
    now = now_utc()
    tr.assess(value=0.5, ts_epoch=100.0, hash_="abc", received_at=now)
    res = tr.assess(value=0.6, ts_epoch=101.0, hash_="abc", received_at=now)
    assert res.is_duplicate


def test_out_of_order_rejected():
    tr = FeedTracker(source="binance", key="BTC")
    now = now_utc()
    tr.assess(value=60000.0, ts_epoch=200.0, received_at=now)
    res = tr.assess(value=60010.0, ts_epoch=150.0, received_at=now)  # ts goes backwards
    assert res.is_out_of_order
    assert not res.accepted
    assert tr.out_of_order == 1


def test_impossible_jump_rejected():
    tr = FeedTracker(source="clob_ws", key="TOK")
    now = now_utc()
    tr.assess(value=0.50, ts_epoch=100.0, received_at=now, max_jump=0.3)
    res = tr.assess(value=0.95, ts_epoch=101.0, received_at=now, max_jump=0.3)  # +0.45 jump
    assert res.is_impossible
    assert not res.accepted


def test_stale_flagged_but_kept():
    tr = FeedTracker(source="binance", key="BTC")
    now = now_utc()
    old_ts = _epoch(now - timedelta(seconds=120))
    res = tr.assess(value=60000.0, ts_epoch=old_ts, received_at=now, stale_after=30.0)
    assert res.is_stale
    assert res.accepted          # stale is flagged, not rejected
    assert tr.stale == 1


def test_reconnect_increments_and_marks_suspect():
    tr = FeedTracker(source="clob_ws", key="TOK")
    tr.on_control("_reconnect")
    assert tr.reconnects == 1
    now = now_utc()
    # an out-of-order tick right after reconnect should be flagged suspect
    tr.assess(value=0.5, ts_epoch=200.0, received_at=now)
    res = tr.assess(value=0.5, ts_epoch=150.0, received_at=now)
    assert res.is_out_of_order
    assert any("post-reconnect" in r for r in res.reasons)


def test_reconnect_counted_once_per_connection_not_per_token():
    """A single connection drop must not be counted once per subscribed token (that inflated the
    reconnect metric ~600x). Per-token trackers track state with count_reconnect=False."""
    conn = FeedTracker(source="clob_ws", key="__conn__")
    tok_a = FeedTracker(source="clob_ws", key="TOKA")
    tok_b = FeedTracker(source="clob_ws", key="TOKB")
    # one drop: count on the connection tracker only
    conn.on_control("_reconnect")
    tok_a.on_control("_reconnect", count_reconnect=False)
    tok_b.on_control("_reconnect", count_reconnect=False)
    assert conn.reconnects == 1
    assert tok_a.reconnects == 0 and tok_b.reconnects == 0
    # per-token still tracks the disconnected state + post-reconnect grace window
    assert tok_a.connected is False
    assert tok_a.reconnect_at_monotonic is not None


def test_health_dict_score():
    tr = FeedTracker(source="binance", key="BTC", asset_symbol="BTC")
    now = now_utc()
    for i in range(10):
        tr.assess(value=60000.0 + i, ts_epoch=100.0 + i, received_at=now)
    h = tr.health_dict()
    assert h["messages"] == 10
    assert 0.0 <= h["health_score"] <= 1.0
    assert h["connected"] is True
