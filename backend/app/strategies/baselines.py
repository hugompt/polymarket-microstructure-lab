"""Concrete baseline & microstructure strategies.

All are SIMULATION signal generators only. Each returns EntryIntents; the simulator handles
pricing/fills/fees/resolution. Strategies that need data the DB doesn't have yet (ticks,
orderbook) simply emit nothing for those markets and the simulator reports them as skipped.
"""
from __future__ import annotations

from .base import (
    REQ_BOOK,
    REQ_CHAINLINK,
    REQ_RESOLUTION,
    REQ_TICKS,
    REQ_WALLET,
    EntryIntent,
    MarketContext,
    Strategy,
)


def _favorite(ctx: MarketContext, at) -> str | None:
    """Book-implied favorite (Up-token mid > 0.5 -> Up) as of ``at``. Returns None when there
    is no point-in-time book (favorite unknowable -> the caller skips, no lookahead, no Up
    default) or on an exact 0.5 tie (genuine coin-flip -> don't bias the stats toward Up)."""
    up = ctx.up_price_at(at)
    if up is None or up == 0.5:
        return None
    return "Up" if up > 0.5 else "Down"


class RandomStrategy(Strategy):
    key = "random"
    name = "Random Up/Down baseline"
    description = "Coin-flip side at open. The honest control every other strategy must beat."
    requires = [REQ_RESOLUTION]

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        side = "Up" if self.rng.random() < 0.5 else "Down"
        return [EntryIntent(side, 0.0, self.size(), "random coin-flip")]


class AlwaysUp(Strategy):
    key = "always_up"
    name = "Always Up"
    description = "Always buy Up at open."
    requires = [REQ_RESOLUTION]

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        return [EntryIntent("Up", 0.0, self.size(), "always up")]


class AlwaysDown(Strategy):
    key = "always_down"
    name = "Always Down"
    description = "Always buy Down at open."
    requires = [REQ_RESOLUTION]

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        return [EntryIntent("Down", 0.0, self.size(), "always down")]


class BuyOpen(Strategy):
    key = "buy_open"
    name = "Buy favorite at open"
    description = "Buy the book-implied favorite at the open (offset 0s). Needs orderbook."
    requires = [REQ_RESOLUTION, REQ_BOOK]

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        t = ctx._t(0.0)
        fav = _favorite(ctx, t)
        return [] if fav is None else [EntryIntent(fav, 0.0, self.size(), "favorite @open")]


class Buy60s(Strategy):
    key = "buy_60s"
    name = "Buy 60s into window"
    description = "Buy the favorite 60 seconds after open. Needs orderbook."
    requires = [REQ_RESOLUTION, REQ_BOOK]

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        t = ctx._t(60.0)
        fav = _favorite(ctx, t)
        return [] if fav is None else [EntryIntent(fav, 60.0, self.size(), "favorite @60s")]


class Buy120s(Strategy):
    key = "buy_120s"
    name = "Buy 120s into window"
    description = "Buy the favorite 120 seconds after open. Needs orderbook."
    requires = [REQ_RESOLUTION, REQ_BOOK]

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        t = ctx._t(120.0)
        fav = _favorite(ctx, t)
        return [] if fav is None else [EntryIntent(fav, 120.0, self.size(), "favorite @120s")]


class MomentumBinance(Strategy):
    key = "momentum_binance"
    name = "Binance momentum"
    description = "Buy Up if Binance spot rose over the lookback, else Down. Needs crypto ticks."
    requires = [REQ_RESOLUTION, REQ_TICKS]
    params_schema = {"lookback_s": 60, "offset_s": 60}

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        offset = float(self.params.get("offset_s", 60))
        lookback = float(self.params.get("lookback_s", 60))
        t1 = ctx._t(offset)
        t0 = ctx._t(max(0.0, offset - lookback))
        a, b = ctx.tick_at("binance", t0), ctx.tick_at("binance", t1)
        if not a or not b or a.price is None or b.price is None or b.price == a.price:
            return []  # no move => no information => no bet (don't default to Up)
        side = "Up" if b.price > a.price else "Down"
        return [EntryIntent(side, offset, self.size(), f"momentum {b.price - a.price:+.2f}")]


class MeanReversionBinance(Strategy):
    key = "mean_reversion_binance"
    name = "Binance mean-reversion"
    description = "Fade the recent Binance move (buy the laggard side). Needs crypto ticks."
    requires = [REQ_RESOLUTION, REQ_TICKS]
    params_schema = {"lookback_s": 60, "offset_s": 60}

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        offset = float(self.params.get("offset_s", 60))
        lookback = float(self.params.get("lookback_s", 60))
        t1 = ctx._t(offset)
        t0 = ctx._t(max(0.0, offset - lookback))
        a, b = ctx.tick_at("binance", t0), ctx.tick_at("binance", t1)
        if not a or not b or a.price is None or b.price is None or b.price == a.price:
            return []  # no move => nothing to fade
        side = "Down" if b.price > a.price else "Up"
        return [EntryIntent(side, offset, self.size(), "mean-reversion fade")]


class ChainlinkBinanceDivergence(Strategy):
    key = "chainlink_binance_divergence"
    name = "Chainlink vs Binance divergence"
    description = "Trade the side implied by Binance leading Chainlink. Needs both feeds."
    requires = [REQ_RESOLUTION, REQ_TICKS, REQ_CHAINLINK]
    params_schema = {"offset_s": 60}

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        offset = float(self.params.get("offset_s", 60))
        t = ctx._t(offset)
        b, c = ctx.tick_at("binance", t), ctx.tick_at("chainlink", t)
        if not b or not c or not b.price or not c.price or b.price == c.price:
            return []  # no divergence => no signal
        # Binance above Chainlink => spot is leading up => bet Up (and vice-versa).
        side = "Up" if b.price > c.price else "Down"
        return [EntryIntent(side, offset, self.size(), f"div {(b.price - c.price):+.2f}")]


class OrderbookImbalance(Strategy):
    key = "orderbook_imbalance"
    name = "Orderbook imbalance"
    description = "Buy the side with heavier top-of-book bid depth. Needs orderbook snapshots."
    requires = [REQ_RESOLUTION, REQ_BOOK]
    params_schema = {"offset_s": 30, "threshold": 0.2}

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        from ..util.normalize import orderbook_imbalance
        offset = float(self.params.get("offset_s", 30))
        threshold = float(self.params.get("threshold", 0.2))
        t = ctx._t(offset)
        up_tok = ctx.token_by_outcome.get("Up")
        if not up_tok:
            return []
        b = ctx.book_as_of(up_tok, t)  # STRICT point-in-time book (no lookahead)
        if not b:
            return []
        imb = orderbook_imbalance({
            "bid_depth_top5": b.bid_depth_top5, "ask_depth_top5": b.ask_depth_top5})
        if imb is None or abs(imb) < threshold:
            return []
        side = "Up" if imb > 0 else "Down"  # bid-heavy on Up token => Up
        return [EntryIntent(side, offset, self.size(), f"imbalance {imb:+.2f}")]


class FollowWallet(Strategy):
    key = "follow_wallet"
    name = "Follow target wallet"
    description = "Copy the tracked wallet's BUYs after a configurable observation delay."
    requires = [REQ_RESOLUTION, REQ_WALLET]
    params_schema = {"delay_s": 2.0}

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        if ctx.market.start_time is None:
            return []
        delay = float(self.params.get("delay_s", 2.0))
        intents: list[EntryIntent] = []
        for tr in ctx.wallet_trades:
            if tr.side != "BUY" or tr.outcome not in ("Up", "Down") or tr.ts_utc is None:
                continue
            offset = (tr.ts_utc - ctx.market.start_time).total_seconds() + delay
            intents.append(EntryIntent(tr.outcome, offset, self.size(),
                                       f"copy wallet {delay:.0f}s late"))
        return intents


class StaleOdds(Strategy):
    key = "stale_odds"
    name = "Stale odds vs spot"
    description = ("Enter when Polymarket top-of-book hasn't moved but Binance/Chainlink spot "
                  "has — the proposed real edge. Needs orderbook + crypto ticks.")
    requires = [REQ_RESOLUTION, REQ_BOOK, REQ_TICKS]
    params_schema = {"offset_s": 30, "lookback_s": 20, "spot_move_bps": 5.0}

    def generate(self, ctx: MarketContext) -> list[EntryIntent]:
        offset = float(self.params.get("offset_s", 30))
        lookback = float(self.params.get("lookback_s", 20))
        move_bps = float(self.params.get("spot_move_bps", 5.0))
        t1 = ctx._t(offset)
        t0 = ctx._t(max(0.0, offset - lookback))
        s0, s1 = ctx.tick_at("binance", t0), ctx.tick_at("binance", t1)
        p0, p1 = ctx.up_price_at(t0), ctx.up_price_at(t1)
        if not s0 or not s1 or not s0.price or not s1.price or p0 is None or p1 is None:
            return []
        spot_ret_bps = (s1.price - s0.price) / s0.price * 10_000
        odds_moved = abs(p1 - p0) > 0.01
        if abs(spot_ret_bps) >= move_bps and not odds_moved:
            # Spot moved but odds are stale -> bet the spot direction.
            side = "Up" if spot_ret_bps > 0 else "Down"
            return [EntryIntent(side, offset, self.size(), f"stale odds; spot {spot_ret_bps:+.1f}bps")]
        return []


ALL_STRATEGIES: list[type[Strategy]] = [
    RandomStrategy, AlwaysUp, AlwaysDown, BuyOpen, Buy60s, Buy120s,
    MomentumBinance, MeanReversionBinance, ChainlinkBinanceDivergence,
    OrderbookImbalance, FollowWallet, StaleOdds,
]
