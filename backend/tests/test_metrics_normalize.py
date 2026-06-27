"""Pure metrics + normalization helpers."""
from __future__ import annotations

import math

import pytest

from app.analysis import metrics
from app.util.normalize import (
    as_json_list,
    dedup_hash,
    normalize_book,
    orderbook_imbalance,
    price_bucket,
    to_float,
)


def test_max_drawdown():
    # cumulative: +10, +5(-5 dd), +15, +5 (-10 dd) -> worst -10
    assert metrics.max_drawdown([10, -5, 10, -10]) == pytest.approx(-10)
    assert metrics.max_drawdown([]) == 0.0
    assert metrics.max_drawdown([5, 5, 5]) == 0.0


def test_profit_factor():
    assert metrics.profit_factor([10, -5, 5, -5]) == pytest.approx(15 / 10)
    assert metrics.profit_factor([1, 2, 3]) == math.inf  # no losses
    assert metrics.profit_factor([]) is None


def test_win_rate_and_avgs():
    pnls = [10, -5, 20, -10]
    assert metrics.win_rate([p > 0 for p in pnls]) == 0.5
    assert metrics.avg_win(pnls) == pytest.approx(15)
    assert metrics.avg_loss(pnls) == pytest.approx(-7.5)


def test_low_sample_flag():
    assert metrics.is_low_sample(5) is True
    assert metrics.is_low_sample(100) is False


def test_summarize_json_safe():
    s = metrics.summarize([1, 2, 3])  # no losses -> inf profit factor must be nulled for JSON
    assert s["profit_factor"] is None
    assert s["n"] == 3


def test_group_breakdown():
    rows = [{"k": "BTC", "pnl": 10, "won": True}, {"k": "BTC", "pnl": -5, "won": False},
            {"k": "ETH", "pnl": 3, "won": True}]
    out = {g["key"]: g for g in metrics.group_breakdown(rows, lambda r: r["k"])}
    assert out["BTC"]["n"] == 2
    assert out["BTC"]["pnl"] == pytest.approx(5)
    assert out["BTC"]["win_rate"] == 0.5


def test_normalize_book():
    book = normalize_book(
        bids=[{"price": "0.01", "size": "100"}, {"price": "0.49", "size": "200"}],
        asks=[{"price": "0.99", "size": "100"}, {"price": "0.51", "size": "300"}],
    )
    assert book["best_bid"] == 0.49      # highest bid
    assert book["best_ask"] == 0.51      # lowest ask
    assert book["mid"] == pytest.approx(0.5)
    assert book["spread"] == pytest.approx(0.02)
    assert book["bid_depth_top5"] == 300
    assert book["ask_depth_top5"] == 400


def test_orderbook_imbalance():
    assert orderbook_imbalance({"bid_depth_top5": 300, "ask_depth_top5": 100}) == pytest.approx(0.5)
    assert orderbook_imbalance({"bid_depth_top5": 0, "ask_depth_top5": 0}) is None


def test_price_bucket():
    assert price_bucket(0.0) == "0-5"
    assert price_bucket(0.97) == "95-100"
    assert price_bucket(0.5) == "50-65"
    assert price_bucket(None) is None


def test_as_json_list_handles_string_and_list():
    assert as_json_list('["Up","Down"]') == ["Up", "Down"]
    assert as_json_list(["a", "b"]) == ["a", "b"]
    assert as_json_list(None) == []


def test_dedup_hash_stable_and_distinct():
    a = dedup_hash("0xtx", "BUY", 0.5, 100)
    b = dedup_hash("0xtx", "BUY", 0.5, 100)
    c = dedup_hash("0xtx", "SELL", 0.5, 100)
    assert a == b
    assert a != c


def test_to_float():
    assert to_float("1.5") == 1.5
    assert to_float(None, 0.0) == 0.0
    assert to_float("nan-ish") is None
