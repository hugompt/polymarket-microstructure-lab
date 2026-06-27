"""Forward (live) paper trading.

SIMULATION ONLY. This package observes LIVE markets via public read-only feeds and simulates
order placement + fills + settlement. It NEVER places a real order, signs anything, or touches a
key. Its purpose: estimate whether a strategy would make money LIVE — and, crucially, how much
of that hinges on latency — by filling a single decision across several "latency accounts" and
settling on the real resolution.
"""
from __future__ import annotations

from .accounts import Decision, LiveBook, PaperOrderState, fill_order, settle_order
from .decide import LIVE_STRATEGIES, decide_live

__all__ = [
    "Decision", "LiveBook", "PaperOrderState", "fill_order", "settle_order",
    "decide_live", "LIVE_STRATEGIES",
]
