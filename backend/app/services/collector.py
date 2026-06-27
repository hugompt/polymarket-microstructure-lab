"""Live microstructure collector.

Feeds (all read-only):
  * CLOB market WebSocket  -> live orderbook (`book`), `price_change`, `last_trade_price`
  * Binance WebSocket      -> spot crypto ticks (robust fallback / "binance" source)
  * RTDS WebSocket         -> Binance + Chainlink ticks (best-effort; tolerant)
  * CLOB /book REST poll   -> periodic validator / fallback when WS is quiet

Design:
  * Every event passes through a per-feed ``FeedTracker`` (stale/dup/out-of-order/jump flags).
  * Raw events are always stored; accepted events also produce clean snapshots / orderbook
    snapshots / ticks.
  * ALL DB writes funnel through ONE batching writer task -> no SQLite lock contention, and
    collector state (FeedHealth) is persisted so restarts keep continuity.
  * Connection count is conservative by default (``ws_max_connections`` = 2), NOT 100-300.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from ..clients.clob import ClobClient
from ..clients.ws_crypto import BinanceWS, RtdsWS
from ..clients.ws_market import ClobMarketWS
from ..config import settings
from ..db import models
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..util.normalize import dedup_hash, normalize_book, to_float
from ..util.timeutil import now_utc
from . import data_quality as dq
from .discovery import run_discovery

log = get_logger("services.collector")


class Collector:
    def __init__(
        self,
        *,
        assets: list[str] | None = None,
        windows: list[int] | None = None,
        duration: float | None = None,
        use_ws: bool = True,
        use_rest_poll: bool = True,
        max_connections: int | None = None,
        rediscover: bool = True,
    ) -> None:
        self.assets = [a.upper() for a in (assets or settings.assets)]
        self.windows = windows or settings.windows_minutes
        self.duration = duration
        self.use_ws = use_ws
        self.use_rest_poll = use_rest_poll
        self.max_connections = max_connections or settings.ws_max_connections
        self.rediscover = rediscover

        self.stop = asyncio.Event()
        self.write_q: asyncio.Queue = asyncio.Queue(maxsize=20000)
        self.trackers: dict[tuple[str, str], dq.FeedTracker] = {}
        self.token_map: dict[str, dict] = {}   # token_id -> {market_id, outcome, asset, window}
        self.tokens: list[str] = []
        self.dropped = 0           # non-critical events dropped under write backpressure
        self.ws_covered = 0        # token count the WS shards subscribed at startup
        self._clob = ClobClient()

    # Critical event kinds are awaited (never dropped); raw/tick may be shed under backpressure
    # so a slow DB writer can never stall the websocket read loop.
    _CRITICAL_KINDS = {"orderbook", "clean", "quality"}

    async def _enqueue(self, item: dict) -> None:
        if item.get("kind") in self._CRITICAL_KINDS:
            await self.write_q.put(item)
            return
        try:
            self.write_q.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped % 500 == 1:
                log.warning("collector_write_backpressure", dropped=self.dropped,
                            qsize=self.write_q.qsize())

    # ------------------------------------------------------------------ trackers
    def tracker(self, source: str, key: str, *, asset=None, market_id=None) -> dq.FeedTracker:
        k = (source, key)
        t = self.trackers.get(k)
        if t is None:
            t = dq.FeedTracker(source=source, key=key, asset_symbol=asset, market_id=market_id)
            self.trackers[k] = t
        else:
            if asset and not t.asset_symbol:
                t.asset_symbol = asset
            if market_id and not t.market_id:
                t.market_id = market_id
        return t

    # ------------------------------------------------------------------ universe
    def _load_universe(self) -> None:
        # Only markets live now or starting within the lead window. Collecting ALL "upcoming"
        # markets (pre-listed ~19h ahead) would mean hundreds of tokens per WS connection, which
        # Polymarket rejects -> reconnect storm. Time-based so it is robust to stale status too.
        now = now_utc()
        lead = timedelta(minutes=settings.collector_lead_minutes)
        with session_scope() as db:
            stmt = select(models.Market).where(
                models.Market.asset_symbol.in_([a.upper() for a in self.assets]),
                models.Market.window_minutes.in_(self.windows),
                models.Market.parse_status == "ok",
                models.Market.enable_order_book.is_(True),
                models.Market.end_time > now,
                models.Market.start_time <= now + lead,
            )
            markets = list(db.scalars(stmt))
            token_map: dict[str, dict] = {}
            for m in markets:
                for o in m.outcomes_rel or []:
                    if o.token_id:
                        token_map[o.token_id] = {
                            "market_id": m.id, "outcome": o.outcome_name,
                            "asset": m.asset_symbol, "window": m.window_minutes,
                        }
            self.token_map = token_map
            self.tokens = list(token_map.keys())
        log.info("collector_universe", markets=len(markets), tokens=len(self.tokens),
                 lead_minutes=settings.collector_lead_minutes)

    # ------------------------------------------------------------------ handlers
    async def _handle_market_event(self, ev: dict) -> None:
        etype = ev.get("event_type")
        if etype in ("_connect", "_disconnect", "_reconnect"):
            # Count the reconnect ONCE (connection-level), not once per subscribed token.
            self.tracker("clob_ws", "__conn__").on_control(etype)
            for tok in self.tokens:
                self.tracker("clob_ws", tok).on_control(etype, count_reconnect=False)
            if etype == "_reconnect":
                await self._enqueue({"kind": "quality", "source": "clob_ws", "token": None,
                                        "event_type": "reconnect", "message": ev.get("error", "reconnect")})
            return
        token = ev.get("token_id")
        if not token:
            return
        meta = self.token_map.get(token, {})
        tr = self.tracker("clob_ws", token, asset=meta.get("asset"), market_id=meta.get("market_id"))
        received = ev.get("received_ts") or now_utc()
        src_ts = ev.get("source_ts")
        src_epoch = src_ts.timestamp() if isinstance(src_ts, datetime) else None

        # Always store raw.
        await self._enqueue({
            "kind": "raw", "market_id": meta.get("market_id"), "token_id": token,
            "source": "clob_ws", "event_type": etype, "source_ts": src_ts, "received_ts": received,
            "raw": ev.get("payload"),
            "dedup": dedup_hash("clob_ws", token, etype, ev.get("book_hash"), str(ev.get("payload"))[:200]),
        })

        if etype == "book":
            book = normalize_book(ev.get("bids"), ev.get("asks"))
            res = tr.assess(value=book.get("mid"), ts_epoch=src_epoch, hash_=ev.get("book_hash"),
                            received_at=received)
            await self._emit_orderbook("clob_ws", token, meta, book, src_ts, received, res, ev.get("book_hash"), ev.get("payload"))
            await self._emit_quality(tr, res, token)
        elif etype == "last_trade_price":
            price = ev.get("price")
            res = tr.assess(value=price, ts_epoch=src_epoch, received_at=received)
            await self._enqueue({
                "kind": "clean", "market_id": meta.get("market_id"), "token_id": token,
                "source": "clob_ws", "event_type": etype, "source_ts": src_ts, "received_ts": received,
                "last_trade_price": price, "res": res,
            })
            await self._emit_quality(tr, res, token)
        # price_change deltas are stored raw; full book snapshots + REST poll carry state.

    async def _handle_crypto_event(self, ev: dict) -> None:
        etype = ev.get("event_type")
        source = ev.get("source", "binance")
        if etype in ("_connect", "_disconnect", "_reconnect"):
            self.tracker(source, "__conn__").on_control(etype)  # count reconnect once per feed
            for asset in self.assets:
                self.tracker(source, asset, asset=asset).on_control(etype, count_reconnect=False)
            return
        asset = ev.get("asset_symbol")
        price = ev.get("price")
        if not asset or price is None:
            return
        tr = self.tracker(source, asset, asset=asset)
        received = ev.get("received_ts") or now_utc()
        src_ts = ev.get("source_ts")
        src_epoch = src_ts.timestamp() if isinstance(src_ts, datetime) else None
        # Crypto jump threshold is relative; convert to absolute on last value.
        jump = (tr.last_value * 0.05) if tr.last_value else 1e18
        res = tr.assess(value=price, ts_epoch=src_epoch, received_at=received, max_jump=jump)
        # High-frequency feeds (Binance @trade) emit many identical-price ticks. They are counted
        # in feed_health but NOT stored as rows: a pure duplicate is byte-identical to the already
        # stored accepted tick, so keeping it adds no analytical value and would bloat the DB to
        # millions of rows on a long run. Genuinely interesting ticks (accepted, or flagged
        # stale/out-of-order/impossible) are still stored.
        if not (res.is_duplicate and not (res.is_stale or res.is_out_of_order or res.is_impossible)):
            await self._enqueue({
                "kind": "tick", "asset": asset, "source": source, "price": price,
                "source_ts": src_ts, "received_ts": received, "res": res, "raw": ev.get("payload"),
            })
        await self._emit_quality(tr, res, None)

    async def _emit_orderbook(self, source, token, meta, book, src_ts, received, res, book_hash, raw):
        # An unchanged book (same hash) on the next poll/push is a pure duplicate: identical to the
        # last stored snapshot, so it adds nothing and would bloat the DB (the REST poll alone
        # repeats every ~1.5s). Count it in feed_health, but only STORE book CHANGES (and genuine
        # anomalies). Replay/enrichment still reconstruct the book from the last accepted snapshot.
        if res is not None and res.is_duplicate and not (
            res.is_stale or res.is_out_of_order or res.is_impossible
        ):
            return
        await self._enqueue({
            "kind": "orderbook", "market_id": meta.get("market_id"), "token_id": token,
            "outcome": meta.get("outcome"), "source": source, "source_ts": src_ts,
            "received_ts": received, "book": book, "book_hash": book_hash, "res": res, "raw": raw,
        })

    async def _emit_quality(self, tr: dq.FeedTracker, res: dq.QualityResult, token) -> None:
        # Only log NOTABLE anomalies as event rows. Duplicates are extremely high-volume on trade
        # feeds and already counted in feed_health, so writing a row per duplicate is pure noise
        # and DB bloat — skip them here (the counter is what the dashboard shows).
        notable = res.is_stale or res.is_out_of_order or res.is_impossible
        if notable:
            etype = ("stale" if res.is_stale else "out_of_order" if res.is_out_of_order
                     else "impossible_jump")
            await self._enqueue({
                "kind": "quality", "source": tr.source, "token": token, "asset": tr.asset_symbol,
                "market_id": tr.market_id, "event_type": etype, "message": "; ".join(res.reasons),
            })

    # ------------------------------------------------------------------ writer
    async def _writer_loop(self) -> None:
        while not (self.stop.is_set() and self.write_q.empty()):
            batch = []
            try:
                item = await asyncio.wait_for(self.write_q.get(), timeout=1.0)
                batch.append(item)
            except asyncio.TimeoutError:
                continue
            while len(batch) < 500:
                try:
                    batch.append(self.write_q.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                self._flush_batch(batch)
            except Exception as exc:  # pragma: no cover
                log.warning("writer_flush_error", error=str(exc), n=len(batch))

    def _flush_batch(self, batch: list[dict]) -> None:
        with session_scope() as db:
            for it in batch:
                kind = it["kind"]
                if kind == "raw":
                    db.add(models.MarketSnapshotRaw(
                        market_id=it.get("market_id"), token_id=it.get("token_id"),
                        source=it["source"], event_type=it.get("event_type"),
                        source_ts=it.get("source_ts"), received_ts=it["received_ts"],
                        processing_ts=now_utc(), dedup_hash=it.get("dedup"), raw=it.get("raw"),
                    ))
                elif kind == "orderbook":
                    self._write_orderbook(db, it)
                elif kind == "clean":
                    res = it.get("res")
                    db.add(models.MarketSnapshotClean(
                        market_id=it.get("market_id"), token_id=it.get("token_id"),
                        source=it["source"], event_type=it.get("event_type"),
                        source_ts=it.get("source_ts"), received_ts=it["received_ts"],
                        last_trade_price=it.get("last_trade_price"),
                        accepted=res.accepted if res else True,
                        is_stale=res.is_stale if res else False,
                        is_duplicate=res.is_duplicate if res else False,
                        is_out_of_order=res.is_out_of_order if res else False,
                    ))
                elif kind == "tick":
                    res = it.get("res")
                    db.add(models.CryptoPriceTick(
                        asset_symbol=it["asset"], source=it["source"], price=it["price"],
                        source_ts=it.get("source_ts"), received_ts=it["received_ts"],
                        is_stale=res.is_stale if res else False,
                        is_duplicate=res.is_duplicate if res else False,
                        is_out_of_order=res.is_out_of_order if res else False,
                        accepted=res.accepted if res else True, raw=it.get("raw"),
                    ))
                elif kind == "quality":
                    db.add(models.DataQualityEvent(
                        ts=now_utc(), market_id=it.get("market_id"), token_id=it.get("token"),
                        asset_symbol=it.get("asset"), source=it["source"],
                        event_type=it["event_type"], severity="warn", message=it.get("message"),
                    ))

    def _write_orderbook(self, db, it) -> None:
        book = it["book"]
        res = it.get("res")
        latency = None
        if it.get("source_ts") is not None:
            latency = (it["received_ts"] - it["source_ts"]).total_seconds() * 1000.0
        snap = models.OrderbookSnapshot(
            market_id=it.get("market_id"), token_id=it.get("token_id"), outcome_name=it.get("outcome"),
            source=it["source"], source_ts=it.get("source_ts"), received_ts=it["received_ts"],
            best_bid=book.get("best_bid"), best_ask=book.get("best_ask"), mid=book.get("mid"),
            spread=book.get("spread"), bid_depth_top5=book.get("bid_depth_top5"),
            ask_depth_top5=book.get("ask_depth_top5"), bid_depth_top10=book.get("bid_depth_top10"),
            ask_depth_top10=book.get("ask_depth_top10"), latency_ms=latency, book_hash=it.get("book_hash"),
            is_stale=res.is_stale if res else False, is_duplicate=res.is_duplicate if res else False,
            is_out_of_order=res.is_out_of_order if res else False,
            accepted=res.accepted if res else True, raw=it.get("raw"),
        )
        db.add(snap)
        db.flush()
        for side, levels in (("bid", book.get("bid_levels", [])), ("ask", book.get("ask_levels", []))):
            for idx, (price, size) in enumerate(levels[:10]):
                db.add(models.OrderbookLevel(
                    snapshot_id=snap.id, side=side, level_index=idx, price=price, size=size
                ))

    # ------------------------------------------------------------------ loops
    async def _rest_poll_loop(self) -> None:
        while not self.stop.is_set():
            for token in list(self.tokens):
                if self.stop.is_set():
                    break
                try:
                    raw = await self._clob.book(token)
                except Exception as exc:
                    log.debug("rest_book_error", token=token[:16], error=str(exc))
                    continue
                book = normalize_book(raw.get("bids"), raw.get("asks"))
                meta = self.token_map.get(token, {})
                tr = self.tracker("clob_rest", token, asset=meta.get("asset"), market_id=meta.get("market_id"))
                received = now_utc()
                book_hash = raw.get("hash")
                res = tr.assess(value=book.get("mid"), ts_epoch=to_float(raw.get("timestamp")),
                                hash_=book_hash, received_at=received)
                await self._emit_orderbook("clob_rest", token, meta, book, None, received, res, book_hash, raw)
                await self._emit_quality(tr, res, token)
            await self._sleep(settings.collector_poll_seconds)

    async def _health_flush_loop(self) -> None:
        while not self.stop.is_set():
            await self._sleep(10.0)
            try:
                with session_scope() as db:
                    for tr in list(self.trackers.values()):
                        dq.upsert_feed_health(db, tr)
            except Exception as exc:  # pragma: no cover
                log.debug("health_flush_error", error=str(exc))

    async def _rediscover_loop(self) -> None:
        while not self.stop.is_set():
            await self._sleep(settings.discovery_poll_seconds)
            try:
                await run_discovery(include_closed=False, max_pages_open=4)
                self._load_universe()
                # WS shards are fixed at startup; the REST poll covers newly-discovered tokens.
                # Surface the gap so it is observable rather than silent.
                if self.use_ws and len(self.tokens) > self.ws_covered:
                    log.info("collector_universe_grew",
                             tokens=len(self.tokens), ws_covered=self.ws_covered,
                             new_on_rest_poll_only=len(self.tokens) - self.ws_covered)
            except Exception as exc:
                log.warning("rediscover_error", error=str(exc))

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _duration_guard(self) -> None:
        if self.duration:
            await self._sleep(self.duration)
            self.stop.set()

    # ------------------------------------------------------------------ run
    async def run(self) -> dict:
        self._load_universe()
        if not self.tokens:
            log.warning("collector_no_tokens",
                        msg="no live/upcoming universe markets with orderbook; run discover first")
        tasks: list[asyncio.Task] = [
            asyncio.create_task(self._writer_loop(), name="writer"),
            asyncio.create_task(self._health_flush_loop(), name="health"),
        ]
        if self.duration:
            tasks.append(asyncio.create_task(self._duration_guard(), name="duration"))
        if self.rediscover:
            tasks.append(asyncio.create_task(self._rediscover_loop(), name="rediscover"))
        if self.use_rest_poll:
            tasks.append(asyncio.create_task(self._rest_poll_loop(), name="rest_poll"))
        if self.use_ws and self.tokens:
            self.ws_covered = len(self.tokens)
            for shard in self._shard_tokens():
                ws = ClobMarketWS(shard)
                tasks.append(asyncio.create_task(ws.run(self._handle_market_event, self.stop),
                                                 name="clob_ws"))
        if self.use_ws:
            tasks.append(asyncio.create_task(
                BinanceWS(self.assets).run(self._handle_crypto_event, self.stop), name="binance"))
            if settings.enable_rtds:
                tasks.append(asyncio.create_task(
                    RtdsWS(self.assets).run(self._handle_crypto_event, self.stop), name="rtds"))

        log.info("collector_start", tasks=[t.get_name() for t in tasks], duration=self.duration)
        try:
            await self.stop.wait()
        finally:
            self.stop.set()
            await asyncio.sleep(0.2)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Final health persist + drain queue.
            await self._final_flush()
            await self._clob.aclose()
        summary = {"tokens": len(self.tokens), "ws_covered": self.ws_covered,
                   "dropped_under_backpressure": self.dropped,
                   "feeds": {k[0] + ":" + (k[1][:8] if k[1] else ""): tr.health_dict()
                             for k, tr in self.trackers.items()}}
        log.info("collector_stopped", tokens=len(self.tokens), feeds=len(self.trackers),
                 dropped=self.dropped)
        return summary

    async def _final_flush(self) -> None:
        batch = []
        while not self.write_q.empty():
            try:
                batch.append(self.write_q.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            try:
                self._flush_batch(batch)
            except Exception as exc:  # pragma: no cover
                log.debug("final_flush_error", error=str(exc))
        try:
            with session_scope() as db:
                for tr in list(self.trackers.values()):
                    dq.upsert_feed_health(db, tr)
        except Exception:
            pass

    def _shard_tokens(self) -> list[list[str]]:
        n = max(1, min(self.max_connections, len(self.tokens)))
        shards: list[list[str]] = [[] for _ in range(n)]
        for i, tok in enumerate(self.tokens):
            shards[i % n].append(tok)
        return [s for s in shards if s]


async def run_collector(**kwargs) -> dict:
    return await Collector(**kwargs).run()
