"""Forward paper-trading engine.

Runs a strategy in REAL TIME against live markets and fills a single decision across several
"latency accounts" so the cost of latency is measured directly (same signal, different ms ->
different fill price & PnL), settling on the real resolution.

Design for testability: all state transitions are plain methods (``on_book``, ``on_spot``,
``decision_tick``, ``fill_tick``, ``settle_tick``) that can be driven with synthetic data in a
unit test. The async ``run()`` is just a thin shell that wires the public read-only WS/REST feeds
to those methods. NOTHING here places a real order.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.fees import FeeSchedule
from ..clients.clob import ClobClient
from ..clients.ws_crypto import BinanceWS
from ..clients.ws_market import ClobMarketWS
from ..config import settings
from ..db import models
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..services.discovery import fetch_current_window_pairs, persist_markets
from ..services.parsing import parse_market
from ..util.normalize import normalize_book
from ..util.timeutil import now_utc
from . import accounts as acc
from .accounts import Decision, LiveBook, PaperOrderState
from .decide import LIVE_STRATEGY_KEYS, LiveMarketState, decide_live

log = get_logger("paper.engine")

DEFAULT_LATENCY_GRID = [0, 40, 100, 250, 500, 1000]


@dataclass
class MarketInfo:
    market_id: int
    condition_id: str | None
    asset: str | None
    window_minutes: int | None
    start_time: datetime
    end_time: datetime
    up_token: str | None
    down_token: str | None
    schedule: FeeSchedule


@dataclass
class PaperConfig:
    strategy_key: str = "stale_odds"
    assets: list[str] = field(default_factory=lambda: list(settings.assets))
    windows: list[int] = field(default_factory=lambda: list(settings.windows_minutes))
    latency_grid_ms: list[int] = field(default_factory=lambda: list(DEFAULT_LATENCY_GRID))
    size: float = 100.0
    fee_scenario: str = "conservative"
    duration_s: float | None = 1800.0
    params: dict = field(default_factory=dict)
    lookback_s: float = 20.0
    entry_after_s: float = 10.0          # don't enter in the first seconds of the window
    entry_before_close_s: float = 30.0   # don't enter too close to resolution
    decision_interval_s: float = 3.0
    fill_interval_s: float = 0.1
    max_slippage: float | None = None
    seed: int = 1234


class PaperEngine:
    def __init__(self, config: PaperConfig):
        self.cfg = config
        import random
        self.rng = random.Random(config.seed)
        self.stop = asyncio.Event()
        self.session_id: int | None = None

        self.books: dict[str, LiveBook] = {}
        self.book_hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=600))   # token -> (ts,LiveBook)
        self.spot_hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))  # asset -> (ts,price)
        self.chainlink: dict[str, tuple] = {}
        self.odds_hist: dict[int, deque] = defaultdict(lambda: deque(maxlen=600))   # market -> (ts,up_mid)
        self.markets: dict[int, MarketInfo] = {}
        self.token_to_market: dict[str, tuple[int, str]] = {}   # token -> (market_id, outcome)
        self.entered: set[int] = set()
        self.orders: list[PaperOrderState] = []
        self.resolutions: dict[str, str] = {}   # condition_id -> resolved_outcome
        self._clob = ClobClient()
        self._ws_task: asyncio.Task | None = None
        self._ws_tokens: list[str] = []

    # ------------------------------------------------------------- state updates
    def on_book(self, token: str, book: LiveBook) -> None:
        self.books[token] = book
        self.book_hist[token].append((book.ts or now_utc(), book))
        mk = self.token_to_market.get(token)
        if mk and mk[1] == "Up" and book.mid is not None:
            self.odds_hist[mk[0]].append((book.ts or now_utc(), book.mid))

    def on_spot(self, asset: str, price: float, ts: datetime) -> None:
        self.spot_hist[asset].append((ts, price))

    def on_chainlink(self, asset: str, price: float, ts: datetime) -> None:
        self.chainlink[asset] = (ts, price)

    def _as_of(self, hist: deque, at: datetime):
        chosen = None
        for ts, val in hist:
            if ts <= at:
                chosen = val
            else:
                break
        return chosen

    def _book_as_of(self, token: str, at: datetime) -> LiveBook | None:
        return self._as_of(self.book_hist.get(token, deque()), at)

    # ------------------------------------------------------------- decision tick
    def _build_state(self, mi: MarketInfo, now: datetime) -> LiveMarketState:
        lookback_at = now - timedelta(seconds=self.cfg.lookback_s)
        up_book = self.books.get(mi.up_token) if mi.up_token else None
        down_book = self.books.get(mi.down_token) if mi.down_token else None
        up_mid_now = up_book.mid if up_book else None
        up_mid_prev = self._as_of(self.odds_hist.get(mi.market_id, deque()), lookback_at)
        spot_now = None
        sh = self.spot_hist.get(mi.asset)
        if sh:
            spot_now = sh[-1][1]
        spot_prev = self._as_of(sh, lookback_at) if sh else None
        cl = self.chainlink.get(mi.asset)
        return LiveMarketState(
            market_id=mi.market_id, asset=mi.asset, window_minutes=mi.window_minutes,
            elapsed_s=(now - mi.start_time).total_seconds(),
            up_book=up_book, down_book=down_book,
            up_mid_now=up_mid_now, up_mid_prev=up_mid_prev,
            spot_now=spot_now, spot_prev=spot_prev,
            chainlink_now=cl[1] if cl else None,
        )

    def decision_tick(self, now: datetime | None = None) -> list[Decision]:
        now = now or now_utc()
        decided: list[Decision] = []
        for mid, mi in list(self.markets.items()):
            if mid in self.entered:
                continue
            if not (mi.start_time <= now < mi.end_time):
                continue
            elapsed = (now - mi.start_time).total_seconds()
            to_close = (mi.end_time - now).total_seconds()
            if elapsed < self.cfg.entry_after_s or to_close < self.cfg.entry_before_close_s:
                continue
            state = self._build_state(mi, now)
            outcome = decide_live(self.cfg.strategy_key, state, self.cfg.params, self.rng)
            if outcome not in ("Up", "Down"):
                continue
            token = mi.up_token if outcome == "Up" else mi.down_token
            book = self.books.get(token) if token else None
            if book is None or book.best_ask is None:
                continue  # can't price an entry right now
            self.entered.add(mid)
            dec = Decision(
                decision_id=f"s{self.session_id}-m{mid}-{int(now.timestamp())}",
                market_id=mid, condition_id=mi.condition_id, asset=mi.asset,
                window_minutes=mi.window_minutes, outcome=outcome, token_id=token,
                decision_ts=now, decision_book=book, size=self.cfg.size,
                reason=f"{self.cfg.strategy_key} elapsed={elapsed:.0f}s",
            )
            decided.append(dec)
            self.orders.extend(acc.make_orders(dec, self.cfg.latency_grid_ms))
        return decided

    # ------------------------------------------------------------- fill tick
    def fill_tick(self, now: datetime | None = None) -> int:
        now = now or now_utc()
        n = 0
        for o in self.orders:
            if o.status != "open" or o.arrive_ts > now:
                continue
            mi = self.markets.get(o.decision.market_id)
            schedule = mi.schedule if mi else FeeSchedule.from_market(None)
            book_at_arrive = self._book_as_of(o.decision.token_id, o.arrive_ts) or \
                self.books.get(o.decision.token_id)
            acc.fill_order(o, book_at_arrive, schedule=schedule,
                           fee_scenario=self.cfg.fee_scenario, max_slippage=self.cfg.max_slippage)
            n += 1
        return n

    # ------------------------------------------------------------- settle tick
    def settle_tick(self, now: datetime | None = None) -> int:
        now = now or now_utc()
        n = 0
        for o in self.orders:
            if o.status != "filled":
                continue
            cond = o.decision.condition_id
            resolved = self.resolutions.get(cond)
            if resolved:
                acc.settle_order(o, resolved, now)
                n += 1
        return n

    # ------------------------------------------------------------- summaries
    def account_summaries(self) -> list[dict]:
        return [acc.account_summary(self.orders, lat) for lat in self.cfg.latency_grid_ms]

    def latency_verdict(self) -> dict:
        sums = {s["latency_ms"]: s for s in self.account_summaries()}
        zero = sums.get(0) or next(iter(sums.values()), {})
        out = {"by_latency": list(sums.values())}
        base = zero.get("realized_pnl")
        if base is not None:
            out["pnl_decay_vs_zero_latency"] = {
                lat: round((s["realized_pnl"] - base), 4) for lat, s in sums.items()}
        return out

    # ------------------------------------------------------------- live wiring
    def _refresh_markets(self) -> None:
        """Load currently-live universe markets from the DB into engine state."""
        now = now_utc()
        with session_scope() as db:
            stmt = select(models.Market).where(
                models.Market.asset_symbol.in_([a.upper() for a in self.cfg.assets]),
                models.Market.window_minutes.in_(self.cfg.windows),
                models.Market.parse_status == "ok",
                models.Market.enable_order_book.is_(True),
                models.Market.start_time <= now + timedelta(seconds=5),
                models.Market.end_time > now,
            )
            for m in db.scalars(stmt):
                if m.id in self.markets:
                    continue
                mi = MarketInfo(
                    market_id=m.id, condition_id=m.condition_id, asset=m.asset_symbol,
                    window_minutes=m.window_minutes, start_time=m.start_time, end_time=m.end_time,
                    up_token=m.up_token_id, down_token=m.down_token_id,
                    schedule=FeeSchedule.from_market(m),
                )
                self.markets[m.id] = mi
                if mi.up_token:
                    self.token_to_market[mi.up_token] = (m.id, "Up")
                if mi.down_token:
                    self.token_to_market[mi.down_token] = (m.id, "Down")
        # prune ended markets from active set (keep entered for settlement)
        for mid, mi in list(self.markets.items()):
            if mi.end_time < now - timedelta(minutes=10):
                self.markets.pop(mid, None)

    def _live_tokens(self) -> list[str]:
        now = now_utc()
        toks: list[str] = []
        for mi in self.markets.values():
            if mi.end_time > now and mi.start_time <= now + timedelta(minutes=5):
                toks += [t for t in (mi.up_token, mi.down_token) if t]
        return toks

    async def _ws_market_handler(self, ev: dict) -> None:
        if ev.get("event_type") != "book":
            return
        token = ev.get("token_id")
        if not token:
            return
        nb = normalize_book(ev.get("bids"), ev.get("asks"))
        self.on_book(token, LiveBook(
            token_id=token, best_bid=nb["best_bid"], best_ask=nb["best_ask"], mid=nb["mid"],
            bid_depth=nb["bid_depth_top5"], ask_depth=nb["ask_depth_top5"],
            ts=ev.get("received_ts") or now_utc()))

    async def _ws_crypto_handler(self, ev: dict) -> None:
        if ev.get("event_type") != "tick":
            return
        asset = ev.get("asset_symbol")
        price = ev.get("price")
        if not asset or price is None:
            return
        ts = ev.get("received_ts") or now_utc()
        if ev.get("source") == "chainlink":
            self.on_chainlink(asset, price, ts)
        else:
            self.on_spot(asset, price, ts)

    async def _book_poll_loop(self) -> None:
        while not self.stop.is_set():
            for token in self._live_tokens():
                if self.stop.is_set():
                    break
                try:
                    raw = await self._clob.book(token)
                except Exception:
                    continue
                nb = normalize_book(raw.get("bids"), raw.get("asks"))
                self.on_book(token, LiveBook(
                    token_id=token, best_bid=nb["best_bid"], best_ask=nb["best_ask"], mid=nb["mid"],
                    bid_depth=nb["bid_depth_top5"], ask_depth=nb["ask_depth_top5"], ts=now_utc()))
            await self._sleep(1.5)

    async def _restart_ws_if_needed(self) -> None:
        toks = self._live_tokens()
        if set(toks) == set(self._ws_tokens) or not toks:
            return
        self._ws_tokens = toks
        if self._ws_task:
            self._ws_task.cancel()
        ws = ClobMarketWS(toks)
        self._ws_task = asyncio.create_task(ws.run(self._ws_market_handler, self.stop), name="paper_ws")

    async def _refresh_loop(self) -> None:
        while not self.stop.is_set():
            try:
                pairs = await fetch_current_window_pairs(assets=self.cfg.assets, windows=self.cfg.windows)
                if pairs:
                    with session_scope() as db:
                        persist_markets(db, pairs)
                self._refresh_markets()
                await self._restart_ws_if_needed()
            except Exception as exc:
                log.warning("paper_refresh_error", error=str(exc))
            await self._sleep(20.0)

    async def _decision_loop(self) -> None:
        while not self.stop.is_set():
            try:
                decided = self.decision_tick()
                if decided:
                    log.info("paper_decisions", n=len(decided),
                             markets=[d.market_id for d in decided])
            except Exception as exc:
                log.warning("paper_decision_error", error=str(exc))
            await self._sleep(self.cfg.decision_interval_s)

    async def _fill_loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.fill_tick()
            except Exception as exc:
                log.warning("paper_fill_error", error=str(exc))
            await self._sleep(self.cfg.fill_interval_s)

    async def _settle_loop(self) -> None:
        while not self.stop.is_set():
            await self._sleep(15.0)
            try:
                await self._fetch_resolutions()
                self.settle_tick()
                self._persist()
            except Exception as exc:
                log.warning("paper_settle_error", error=str(exc))

    async def _fetch_resolutions(self) -> None:
        from ..clients.gamma import GammaClient
        now = now_utc()
        need = {o.decision.condition_id for o in self.orders
                if o.status == "filled" and o.decision.condition_id not in self.resolutions}
        # resolve only markets whose window has ended
        ended = {mi.condition_id for mi in self.markets.values() if mi.end_time <= now}
        need = {c for c in need if c in ended or True}
        if not need:
            return
        slugs = {}
        with session_scope() as db:
            for cond in need:
                m = db.scalar(select(models.Market).where(models.Market.condition_id == cond))
                if m and m.resolved_outcome:
                    self.resolutions[cond] = m.resolved_outcome
                elif m and m.slug:
                    slugs[cond] = m.slug
        if not slugs:
            return
        client = GammaClient()
        try:
            for cond, slug in slugs.items():
                try:
                    evs = await client.events_by_slug(slug)
                except Exception:
                    continue
                for ev in evs:
                    for mk in ev.get("markets", []) or []:
                        p = parse_market(mk, ev)
                        if p.resolved_outcome:
                            self.resolutions[cond] = p.resolved_outcome
        finally:
            await client.aclose()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _duration_guard(self) -> None:
        if self.cfg.duration_s:
            await self._sleep(self.cfg.duration_s)
            self.stop.set()

    # ------------------------------------------------------------- persistence
    def _start_session(self) -> int:
        with session_scope() as db:
            s = models.PaperSession(
                strategy_key=self.cfg.strategy_key,
                label=f"{self.cfg.strategy_key} live paper ({len(self.cfg.latency_grid_ms)} latencies)",
                params=self.cfg.params, assets=self.cfg.assets, windows=self.cfg.windows,
                latency_grid_ms=self.cfg.latency_grid_ms, size=self.cfg.size,
                fill_model="taker", fee_scenario=self.cfg.fee_scenario,
                started_at=now_utc(), status="running",
                config={"lookback_s": self.cfg.lookback_s, "entry_after_s": self.cfg.entry_after_s,
                        "entry_before_close_s": self.cfg.entry_before_close_s,
                        "decision_interval_s": self.cfg.decision_interval_s,
                        "max_slippage": self.cfg.max_slippage},
            )
            db.add(s)
            db.flush()
            self.session_id = s.id
        return self.session_id

    def _persist(self) -> None:
        """Delete + re-insert this session's orders (modest N) and append an equity snapshot."""
        if self.session_id is None:
            return
        now = now_utc()
        with session_scope() as db:
            db.query(models.PaperOrder).filter(
                models.PaperOrder.session_id == self.session_id).delete()
            for o in self.orders:
                d = o.decision
                db.add(models.PaperOrder(
                    session_id=self.session_id, decision_id=d.decision_id, latency_ms=o.latency_ms,
                    market_id=d.market_id, condition_id=d.condition_id, asset_symbol=d.asset,
                    window_minutes=d.window_minutes, outcome=d.outcome,
                    decision_ts=d.decision_ts, decision_price=d.decision_book.best_ask,
                    decision_mid=d.decision_book.mid, arrive_ts=o.arrive_ts,
                    filled=o.status in ("filled", "settled"), fill_price=o.fill_price,
                    fill_size=o.fill_size, spread_cost=o.spread_cost,
                    slippage_vs_decision=o.slippage_vs_decision, fees=o.fees, status=o.status,
                    resolved_outcome=o.resolved_outcome, won=o.won, pnl=o.pnl,
                    settle_ts=o.settle_ts, reason=o.reason, raw=o.raw))
            for s in self.account_summaries():
                db.add(models.PaperAccountEquity(
                    session_id=self.session_id, latency_ms=s["latency_ms"], ts=now,
                    realized_pnl=s["realized_pnl"], fees_paid=s["fees_paid"],
                    n_decisions=s["n_decisions"], n_filled=s["n_filled"], n_open=0,
                    n_settled=s["n_settled"], n_won=s["n_won"]))

    def _finish_session(self) -> None:
        if self.session_id is None:
            return
        with session_scope() as db:
            s = db.get(models.PaperSession, self.session_id)
            if s:
                s.status = "done"
                s.stopped_at = now_utc()
                s.duration_s = (s.stopped_at - s.started_at).total_seconds() if s.started_at else None

    # ------------------------------------------------------------- run
    async def run(self) -> dict:
        if self.cfg.strategy_key not in LIVE_STRATEGY_KEYS:
            raise ValueError(f"strategy '{self.cfg.strategy_key}' not available for live paper "
                             f"trading; choose from {sorted(LIVE_STRATEGY_KEYS)}")
        if self.session_id is None:   # may be pre-created by the API before launch
            self._start_session()
        self._refresh_markets()
        await self._restart_ws_if_needed()
        tasks = [
            asyncio.create_task(self._refresh_loop(), name="refresh"),
            asyncio.create_task(self._book_poll_loop(), name="book_poll"),
            asyncio.create_task(self._decision_loop(), name="decision"),
            asyncio.create_task(self._fill_loop(), name="fill"),
            asyncio.create_task(self._settle_loop(), name="settle"),
            asyncio.create_task(BinanceWS(self.cfg.assets).run(self._ws_crypto_handler, self.stop),
                                name="binance"),
        ]
        if self.cfg.duration_s:
            tasks.append(asyncio.create_task(self._duration_guard(), name="duration"))
        log.info("paper_start", session=self.session_id, strategy=self.cfg.strategy_key,
                 latencies=self.cfg.latency_grid_ms, duration=self.cfg.duration_s)
        try:
            await self.stop.wait()
        finally:
            self.stop.set()
            await asyncio.sleep(0.2)
            for t in tasks:
                t.cancel()
            if self._ws_task:
                self._ws_task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self._fetch_resolutions()
                self.settle_tick()
            except Exception:
                pass
            self._persist()
            self._finish_session()
            await self._clob.aclose()
        verdict = self.latency_verdict()
        log.info("paper_stopped", session=self.session_id,
                 orders=len(self.orders), settled=sum(1 for o in self.orders if o.status == "settled"))
        return {"session_id": self.session_id, **verdict,
                "n_decisions": len(self.entered), "n_orders": len(self.orders)}


async def run_paper_session(config: PaperConfig) -> dict:
    return await PaperEngine(config).run()
