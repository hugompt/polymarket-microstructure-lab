"""Strategy abstractions.

A Strategy looks at one market's context (resolution, orderbook snapshots, crypto ticks, any
tracked-wallet trades) and emits zero or more ``EntryIntent``s: which outcome to buy and at
what offset into the window. The simulator then prices, fills, fees and resolves each intent.

Strategies declare ``requires`` (data dependencies) so the simulator can honestly report which
markets were skipped for lack of data — never silently pretending coverage it doesn't have.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..db import models

# data requirement tokens
REQ_RESOLUTION = "resolution"
REQ_BOOK = "orderbook"
REQ_TICKS = "binance_ticks"
REQ_CHAINLINK = "chainlink_ticks"
REQ_WALLET = "wallet_trades"


@dataclass
class EntryIntent:
    outcome: str            # "Up" | "Down"
    offset_seconds: float   # seconds after market open to attempt entry
    size: float
    reason: str = ""


@dataclass
class MarketContext:
    market: models.Market
    token_by_outcome: dict[str, str]                 # {"Up": token_id, "Down": token_id}
    books_by_token: dict[str, list[models.OrderbookSnapshot]]  # sorted by received_ts asc
    ticks_by_source: dict[str, list[models.CryptoPriceTick]]   # {"binance": [...], ...}
    wallet_trades: list[models.Trade] = field(default_factory=list)

    @property
    def resolved_outcome(self) -> str | None:
        return self.market.resolved_outcome

    def has(self, req: str) -> bool:
        if req == REQ_RESOLUTION:
            return bool(self.market.resolved_outcome)
        if req == REQ_BOOK:
            return any(self.books_by_token.values())
        if req == REQ_TICKS:
            return bool(self.ticks_by_source.get("binance"))
        if req == REQ_CHAINLINK:
            return bool(self.ticks_by_source.get("chainlink"))
        if req == REQ_WALLET:
            return bool(self.wallet_trades)
        return True

    # --- time-indexed lookups (used by strategies & the simulator) ---
    def _t(self, offset_seconds: float):
        from datetime import timedelta
        if self.market.start_time is None:
            return None
        return self.market.start_time + timedelta(seconds=offset_seconds)

    def book_as_of(self, token: str, at) -> models.OrderbookSnapshot | None:
        """STRICT point-in-time book: the most recent snapshot at-or-before ``at``, or None.
        Used for strategy SIGNALS so a decision never sees a future snapshot (no lookahead)."""
        books = self.books_by_token.get(token) or []
        chosen = None
        for b in books:
            if b.received_ts is not None and at is not None and b.received_ts <= at:
                chosen = b
            else:
                break
        return chosen

    def book_at(self, token: str, at) -> models.OrderbookSnapshot | None:
        """LENIENT book for FILL PRICING only: falls back to the earliest snapshot when none
        exists at-or-before ``at``. The fill is then flagged low/med fidelity by the simulator.
        Do NOT use this for signals — it can leak a future book."""
        return self.book_as_of(token, at) or (
            (self.books_by_token.get(token) or [None])[0]
        )

    def up_price_at(self, at) -> float | None:
        """Up-token mid as of ``at`` (STRICT — for signal logic). None if no past snapshot."""
        up_tok = self.token_by_outcome.get("Up")
        if not up_tok:
            return None
        b = self.book_as_of(up_tok, at)
        return b.mid if b else None

    def tick_at(self, source: str, at) -> models.CryptoPriceTick | None:
        ticks = self.ticks_by_source.get(source) or []
        chosen = None
        for t in ticks:
            if t.received_ts is not None and at is not None and t.received_ts <= at:
                chosen = t
            else:
                break
        return chosen


class Strategy(ABC):
    key: str = "base"
    name: str = "Base"
    description: str = ""
    requires: list[str] = [REQ_RESOLUTION]
    params_schema: dict = {}

    def __init__(self, params: dict | None = None, *, rng: random.Random | None = None):
        self.params = params or {}
        self.rng = rng or random.Random(self.params.get("seed", 1234))

    def missing_requirements(self, ctx: MarketContext) -> list[str]:
        return [r for r in self.requires if not ctx.has(r)]

    @abstractmethod
    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        ...

    # convenience
    def size(self) -> float:
        return float(self.params.get("size", 100.0))
