"""Live decision rules for forward paper trading.

Each rule looks at a market's CURRENT live state (outcome unknown) and returns an outcome to buy
("Up"/"Down") or None (no trade). These mirror the backtest strategies but evaluate at "now"
against live in-memory state instead of replaying recorded history. The engine enforces one
entry per market per session and any timing gate.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .accounts import LiveBook


@dataclass
class LiveMarketState:
    market_id: int | None
    asset: str | None
    window_minutes: int | None
    elapsed_s: float                 # seconds since the window opened
    up_book: LiveBook | None
    down_book: LiveBook | None
    up_mid_now: float | None         # current Up-token mid (implied P(Up))
    up_mid_prev: float | None        # Up mid ~lookback_s ago
    spot_now: float | None           # Binance spot now
    spot_prev: float | None          # Binance spot ~lookback_s ago
    chainlink_now: float | None = None


def _favorite(state: LiveMarketState) -> str | None:
    if state.up_mid_now is None or state.up_mid_now == 0.5:
        return None
    return "Up" if state.up_mid_now > 0.5 else "Down"


def _imbalance(book: LiveBook | None) -> float | None:
    if not book or not book.bid_depth or not book.ask_depth:
        return None
    total = book.bid_depth + book.ask_depth
    if total <= 0:
        return None
    return (book.bid_depth - book.ask_depth) / total


def decide_live(strategy_key: str, state: LiveMarketState, params: dict, rng: random.Random) -> str | None:
    p = params or {}

    if strategy_key == "random":
        return "Up" if rng.random() < 0.5 else "Down"

    if strategy_key == "always_up":
        return "Up"
    if strategy_key == "always_down":
        return "Down"

    if strategy_key == "buy_favorite":
        return _favorite(state)

    if strategy_key == "momentum":
        if state.spot_now is None or state.spot_prev is None or state.spot_now == state.spot_prev:
            return None
        return "Up" if state.spot_now > state.spot_prev else "Down"

    if strategy_key == "mean_reversion":
        if state.spot_now is None or state.spot_prev is None or state.spot_now == state.spot_prev:
            return None
        return "Down" if state.spot_now > state.spot_prev else "Up"

    if strategy_key == "divergence":
        if state.spot_now is None or state.chainlink_now is None or state.spot_now == state.chainlink_now:
            return None
        return "Up" if state.spot_now > state.chainlink_now else "Down"

    if strategy_key == "orderbook_imbalance":
        threshold = float(p.get("threshold", 0.2))
        imb = _imbalance(state.up_book)
        if imb is None or abs(imb) < threshold:
            return None
        return "Up" if imb > 0 else "Down"

    if strategy_key == "stale_odds":
        # The proposed real edge: spot has moved but the Polymarket odds haven't repriced yet.
        move_bps = float(p.get("spot_move_bps", 5.0))
        odds_tol = float(p.get("odds_move_tol", 0.01))
        if (state.spot_now is None or state.spot_prev is None or not state.spot_prev
                or state.up_mid_now is None or state.up_mid_prev is None):
            return None
        spot_ret_bps = (state.spot_now - state.spot_prev) / state.spot_prev * 10_000
        odds_moved = abs(state.up_mid_now - state.up_mid_prev) > odds_tol
        if abs(spot_ret_bps) >= move_bps and not odds_moved:
            return "Up" if spot_ret_bps > 0 else "Down"
        return None

    return None


# Strategies runnable in LIVE paper trading (subset/adaptation of the backtest registry).
LIVE_STRATEGIES = [
    {"key": "stale_odds", "name": "Stale odds vs spot",
     "needs": ["orderbook", "binance"], "params": {"spot_move_bps": 5.0, "odds_move_tol": 0.01}},
    {"key": "momentum", "name": "Binance momentum", "needs": ["binance"], "params": {"lookback_s": 20}},
    {"key": "mean_reversion", "name": "Binance mean-reversion", "needs": ["binance"], "params": {"lookback_s": 20}},
    {"key": "divergence", "name": "Binance vs Chainlink", "needs": ["binance", "chainlink"], "params": {}},
    {"key": "orderbook_imbalance", "name": "Orderbook imbalance",
     "needs": ["orderbook"], "params": {"threshold": 0.2}},
    {"key": "buy_favorite", "name": "Buy favorite", "needs": ["orderbook"], "params": {}},
    {"key": "always_up", "name": "Always Up", "needs": [], "params": {}},
    {"key": "always_down", "name": "Always Down", "needs": [], "params": {}},
    {"key": "random", "name": "Random baseline", "needs": [], "params": {}},
]

LIVE_STRATEGY_KEYS = {s["key"] for s in LIVE_STRATEGIES}
