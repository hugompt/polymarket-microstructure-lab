"""Real-time crypto spot prices.

Two sources:
  * BinanceWS — robust, public combined trade stream (the reliable fallback / "binance" feed).
  * RtdsWS    — Polymarket RTDS real-time data service (Binance + Chainlink). The exact RTDS
                protocol may evolve; this client is tolerant: it tries a generic subscribe and
                logs unknown messages rather than crashing, mapping recognised payloads to ticks.
"""
from __future__ import annotations

import json
from typing import Any

from ..config import settings
from ..util.timeutil import epoch_to_utc, now_utc
from .ws_base import BaseWSClient

# Asset symbol -> Binance spot pair (lowercase for stream names).
BINANCE_PAIRS = {
    "BTC": "btcusdt", "ETH": "ethusdt", "SOL": "solusdt",
    "XRP": "xrpusdt", "DOGE": "dogeusdt", "BNB": "bnbusdt",
}


class BinanceWS(BaseWSClient):
    name = "binance"

    def __init__(self, assets: list[str], *, url: str | None = None):
        super().__init__(url or settings.binance_ws_url, ping_text=None)
        self.assets = [a.upper() for a in assets]
        self._pair_to_asset = {
            BINANCE_PAIRS[a].upper(): a for a in self.assets if a in BINANCE_PAIRS
        }
        streams = "/".join(f"{BINANCE_PAIRS[a]}@trade" for a in self.assets if a in BINANCE_PAIRS)
        sep = "&" if "?" in self.url else "?"
        self.url = f"{self.url}{sep}streams={streams}" if streams else self.url

    def subscribe_messages(self):
        return []  # streams are in the URL

    def parse(self, raw: Any) -> list[dict]:
        if not isinstance(raw, dict):
            return []
        data = raw.get("data", raw)
        if not isinstance(data, dict) or "p" not in data:
            return []
        pair = str(data.get("s", "")).upper()
        asset = self._pair_to_asset.get(pair)
        if not asset:
            return []
        ts_ms = data.get("T") or data.get("E")
        return [{
            "event_type": "tick",
            "source": "binance",
            "asset_symbol": asset,
            "price": _f(data.get("p")),
            "source_ts": epoch_to_utc(_ms(ts_ms)),
            "received_ts": now_utc(),
            "payload": data,
        }]


class RtdsWS(BaseWSClient):
    # The RTDS socket delivers Chainlink prices (Polymarket's resolution feed), so we label the
    # feed "chainlink" consistently for both its connection status and its ticks. Otherwise the
    # dashboard would show a confusing "rtds" row stuck at 0 next to a separate "chainlink" row.
    name = "chainlink"

    def __init__(self, assets: list[str], *, url: str | None = None):
        super().__init__(url or settings.rtds_ws_url, ping_text="ping", ping_interval=15.0)
        self.assets = [a.upper() for a in assets]

    def subscribe_messages(self):
        # Per docs.polymarket.com/developers/RTDS: subscribe to the CHAINLINK feed (this is the
        # price source Polymarket actually resolves these crypto Up/Down markets on). Binance
        # prices come from the dedicated BinanceWS, so we don't duplicate them here. `filters` is
        # a JSON *string* with a single symbol like {"symbol":"btc/usd"}.
        return [{
            "action": "subscribe",
            "subscriptions": [
                {"topic": "crypto_prices_chainlink", "type": "*",
                 "filters": json.dumps({"symbol": f"{a.lower()}/usd"})}
                for a in self.assets
            ],
        }]

    def parse(self, raw: Any) -> list[dict]:
        # Observed RTDS shape (chainlink subscription):
        #   {"topic":"crypto_prices","type":"subscribe","timestamp":...,
        #    "payload":{"symbol":"eth/usd","data":[{"timestamp":...,"value":...}, ...]}}
        # The payload carries a rolling 1-second history; we take the latest point. (`type:update`
        # messages may instead carry a single payload.value.) This client subscribes to Chainlink
        # only, so source is always "chainlink" (the response topic label is not distinctive).
        events = raw if isinstance(raw, list) else [raw]
        out: list[dict] = []
        for ev in events:
            if not isinstance(ev, dict) or "_control" in ev or "_unparsed" in ev:
                continue
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
            asset = _rtds_asset(payload.get("symbol"))
            value = ts = None
            data = payload.get("data")
            if isinstance(data, list) and data:
                last = data[-1]
                if isinstance(last, dict):
                    value = _f(last.get("value"))
                    ts = last.get("timestamp")
            if value is None:
                value = _f(payload.get("value") if payload.get("value") is not None else payload.get("price"))
                ts = payload.get("timestamp") or ev.get("timestamp")
            if not asset or value is None:
                self.log.debug("rtds_unmapped", payload=str(ev)[:200])
                continue
            out.append({
                "event_type": "tick",
                "source": "chainlink",
                "asset_symbol": asset,
                "price": value,
                "source_ts": epoch_to_utc(_ms(ts)),
                "received_ts": now_utc(),
                "payload": {"symbol": payload.get("symbol")},  # keep raw lean (data array is large)
            })
        return out


def _rtds_asset(symbol) -> str | None:
    """Map an RTDS symbol to our asset code: 'btc/usd' (chainlink) or 'btcusdt' (binance) -> 'BTC'."""
    if not symbol:
        return None
    s = str(symbol).lower().strip()
    if "/" in s:                       # chainlink: btc/usd
        return s.split("/")[0].upper() or None
    for suffix in ("usdt", "usdc", "usd"):  # binance: btcusdt
        if s.endswith(suffix):
            return s[: -len(suffix)].upper() or None
    return s.upper()


def _ms(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f / 1000.0 if f > 1e12 else f


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
