"""Tolerant client tests via httpx.MockTransport — NO network. Covers parsing, retry, budget."""
from __future__ import annotations

import httpx
import pytest

from app.clients.base import BudgetExceededError, RequestBudget
from app.clients.clob import ClobClient
from app.clients.data_api import DataApiClient
from app.clients.gamma import GammaClient
from app.config import Settings
from tests.conftest import load_fixture

FAST = Settings(backoff_base_seconds=0.001, backoff_cap_seconds=0.01,
                rate_limit_per_sec=10000, rate_limit_burst=1000, max_retries=3)


def _client(cls, handler, **kw):
    return cls(settings=FAST, transport=httpx.MockTransport(handler),
               budget=RequestBudget(1000), persist_logs=False, **kw)


async def test_gamma_markets_tolerant_list():
    fixture = load_fixture("gamma_markets.json")

    def handler(req):
        return httpx.Response(200, json=fixture)

    c = _client(GammaClient, handler)
    out = await c.markets()
    await c.aclose()
    assert isinstance(out, list) and out
    assert "conditionId" in out[0]


async def test_gamma_tolerant_dict_wrapper():
    def handler(req):
        return httpx.Response(200, json={"data": [{"id": "1"}, {"id": "2"}], "extra_unknown": 9})

    c = _client(GammaClient, handler)
    out = await c.events()
    await c.aclose()
    assert len(out) == 2  # unwrapped from {"data": [...]}, unknown keys ignored


async def test_data_trades_and_value():
    trades = load_fixture("data_trades.json")
    value = load_fixture("data_value.json")

    def handler(req):
        if req.url.path == "/trades":
            return httpx.Response(200, json=trades)
        if req.url.path == "/value":
            return httpx.Response(200, json=value)
        return httpx.Response(404, json=[])

    c = _client(DataApiClient, handler)
    t = await c.trades("0xabc")
    v = await c.value("0xabc")
    await c.aclose()
    assert t and t[0]["side"] in ("BUY", "SELL")
    assert isinstance(v, float)


async def test_clob_book_and_midpoint():
    book = load_fixture("clob_book.json")

    def handler(req):
        if req.url.path == "/book":
            return httpx.Response(200, json=book)
        if req.url.path == "/midpoint":
            return httpx.Response(200, json={"mid": "0.5"})
        return httpx.Response(404, json={})

    c = _client(ClobClient, handler)
    b = await c.book("tok")
    mid = await c.midpoint("tok")
    await c.aclose()
    assert "bids" in b and "asks" in b
    assert mid == 0.5


async def test_retry_on_429_then_success():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(429, json={"err": "rate"})
        return httpx.Response(200, json=[{"ok": True}])

    c = _client(GammaClient, handler)
    out = await c.markets()
    await c.aclose()
    assert out == [{"ok": True}]
    assert state["n"] == 3  # retried twice, succeeded on third


async def test_budget_exhausted_raises():
    def handler(req):
        return httpx.Response(200, json=[])

    c = GammaClient(settings=FAST, transport=httpx.MockTransport(handler),
                    budget=RequestBudget(2), persist_logs=False)
    await c.markets()
    await c.markets()
    with pytest.raises(BudgetExceededError):
        await c.markets()
    await c.aclose()


async def test_non_retryable_404_raises():
    def handler(req):
        return httpx.Response(404, json={"err": "nope"})

    c = _client(GammaClient, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await c.events()  # 404 is non-retryable -> propagates
    await c.aclose()


def test_rtds_parses_chainlink_snapshot():
    """Regression: RTDS chainlink message = {payload:{symbol, data:[{timestamp,value}]}}.
    Parser must map symbol -> asset, take the latest data point, and tag source=chainlink."""
    from app.clients.ws_crypto import RtdsWS, _rtds_asset
    assert _rtds_asset("btc/usd") == "BTC" and _rtds_asset("ethusdt") == "ETH"
    ws = RtdsWS(["BTC"])
    msg = {"topic": "crypto_prices", "type": "subscribe", "timestamp": 1782220075756,
           "payload": {"symbol": "eth/usd",
                       "data": [{"timestamp": 1782220074000, "value": 1650.7},
                                {"timestamp": 1782220075000, "value": 1651.9}]}}
    out = ws.parse(msg)
    assert len(out) == 1
    assert out[0]["source"] == "chainlink"
    assert out[0]["asset_symbol"] == "ETH"
    assert out[0]["price"] == 1651.9  # latest point in the rolling window


def test_binance_ws_parses_combined_stream():
    from app.clients.ws_crypto import BinanceWS
    ws = BinanceWS(["BTC"])
    msg = {"stream": "btcusdt@trade",
           "data": {"e": "trade", "s": "BTCUSDT", "p": "62130.5", "T": 1782220075000}}
    out = ws.parse(msg)
    assert len(out) == 1 and out[0]["source"] == "binance"
    assert out[0]["asset_symbol"] == "BTC" and out[0]["price"] == 62130.5


async def test_market_by_id_swallows_errors_returns_none():
    def handler(req):
        return httpx.Response(500, json={"err": "boom"})

    c = _client(GammaClient, handler)
    assert await c.market_by_id("123") is None  # tolerant: returns None, not raises
    await c.aclose()
