"""Market discovery: find & keep updated crypto Up/Down markets (5m / 15m, configurable).

Strategy: page Gamma ``/events?tag=crypto`` (newest first), walk nested markets, keep those
that parse as crypto Up/Down. Markets that don't parse cleanly are still stored with
``parse_status="uncertain"`` and a note (never silently dropped). Upsert is keyed on
``condition_id`` (falling back to slug) so re-running discovery refreshes, not duplicates.

IO (async network) and persistence (sync DB) are separated so no session is held across an
await.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clients.gamma import GammaClient
from ..config import settings
from ..db import models
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..util.normalize import to_float
from ..util.timeutil import now_utc
from .parsing import MarketParse, looks_like_crypto_updown, parse_market

log = get_logger("services.discovery")


async def fetch_crypto_updown(
    *, include_closed: bool = True, max_pages_open: int = 10, max_pages_closed: int = 3
) -> list[tuple[dict, dict]]:
    """Return list of (market_raw, event_raw) pairs that look like crypto Up/Down markets."""
    pairs: list[tuple[dict, dict]] = []
    client = GammaClient()
    try:
        async def collect(closed: bool, max_pages: int):
            count = 0
            async for ev in client.iter_events(
                tag="crypto", closed="true" if closed else "false",
                order="startDate", ascending="false", page_size=100, max_pages=max_pages,
            ):
                for mk in ev.get("markets", []) or []:
                    if isinstance(mk, dict) and looks_like_crypto_updown(mk, ev):
                        pairs.append((mk, ev))
                        count += 1
            return count

        n_open = await collect(False, max_pages_open)
        n_closed = await collect(True, max_pages_closed) if include_closed else 0
        log.info("discovery_fetch", open_markets=n_open, closed_markets=n_closed)
    finally:
        await client.aclose()
    return pairs


async def fetch_current_window_pairs(
    *, assets: list[str] | None = None, windows: list[int] | None = None,
    lookahead: int = 3, lookback: int = 1,
) -> list[tuple[dict, dict]]:
    """Deterministically fetch the CURRENT + next ``lookahead`` (and last ``lookback``) window
    markets per asset/window by computing window-aligned slugs.

    Why: Polymarket pre-lists these markets ~19h ahead, so newest-first paging only ever sees
    far-future markets and NEVER the one whose window contains *now*. Slug starts are aligned to
    window boundaries (5m -> multiples of 300s), so the live/soon markets are addressable directly.
    """
    assets = [a.lower() for a in (assets or settings.assets)]
    windows = windows or settings.windows_minutes
    now = int(now_utc().timestamp())
    slugs: list[str] = []
    for asset in assets:
        for wmin in windows:
            w = wmin * 60
            cur = (now // w) * w
            for k in range(-lookback, lookahead + 1):
                slugs.append(f"{asset}-updown-{wmin}m-{cur + k * w}")

    pairs: list[tuple[dict, dict]] = []
    client = GammaClient()
    try:
        for slug in slugs:
            try:
                events = await client.events_by_slug(slug)
            except Exception as exc:
                log.debug("current_window_fetch_error", slug=slug, error=str(exc))
                continue
            for ev in events:
                for mk in ev.get("markets", []) or []:
                    if isinstance(mk, dict) and looks_like_crypto_updown(mk, ev):
                        pairs.append((mk, ev))
    finally:
        await client.aclose()
    log.info("current_window_fetch", slugs=len(slugs), markets=len(pairs))
    return pairs


def _map_market_fields(m: models.Market, raw: dict, event: dict, parse: MarketParse) -> None:
    m.gamma_market_id = str(raw.get("id")) if raw.get("id") is not None else m.gamma_market_id
    m.event_id = str(event.get("id")) if event.get("id") is not None else m.event_id
    m.condition_id = raw.get("conditionId") or m.condition_id
    m.question_id = raw.get("questionID") or raw.get("questionId") or m.question_id
    m.slug = raw.get("slug") or m.slug
    m.event_slug = event.get("slug") or raw.get("eventSlug") or m.event_slug
    m.title = raw.get("question") or event.get("title") or m.title
    m.question = raw.get("question") or m.question

    m.asset_symbol = parse.asset_symbol or m.asset_symbol
    m.window_minutes = parse.window_minutes if parse.window_minutes is not None else m.window_minutes
    m.start_time = parse.start_time or m.start_time
    m.end_time = parse.end_time or m.end_time
    m.start_epoch = parse.start_epoch if parse.start_epoch is not None else m.start_epoch
    m.end_epoch = parse.end_epoch if parse.end_epoch is not None else m.end_epoch

    m.outcomes = parse.outcomes or m.outcomes
    m.clob_token_ids = parse.clob_token_ids or m.clob_token_ids
    m.up_token_id = parse.up_token_id or m.up_token_id
    m.down_token_id = parse.down_token_id or m.down_token_id

    m.enable_order_book = raw.get("enableOrderBook", m.enable_order_book)
    m.accepting_orders = raw.get("acceptingOrders", m.accepting_orders)
    m.active = raw.get("active", m.active)
    m.closed = raw.get("closed", m.closed)
    m.archived = raw.get("archived", m.archived)

    m.fee_schedule = raw.get("feeSchedule") if raw.get("feeSchedule") is not None else m.fee_schedule
    m.fee_type = raw.get("feeType") or m.fee_type
    m.fees_enabled = raw.get("feesEnabled", m.fees_enabled)
    m.maker_base_fee = to_float(raw.get("makerBaseFee"), m.maker_base_fee)
    m.taker_base_fee = to_float(raw.get("takerBaseFee"), m.taker_base_fee)
    m.rewards_min_size = to_float(raw.get("rewardsMinSize"), m.rewards_min_size)
    m.rewards_max_spread = to_float(raw.get("rewardsMaxSpread"), m.rewards_max_spread)

    m.neg_risk = raw.get("negRisk", m.neg_risk)
    m.tick_size = to_float(raw.get("orderPriceMinTickSize"), m.tick_size)
    m.order_min_size = to_float(raw.get("orderMinSize"), m.order_min_size)

    m.best_bid = to_float(raw.get("bestBid"), m.best_bid)
    m.best_ask = to_float(raw.get("bestAsk"), m.best_ask)
    m.spread = to_float(raw.get("spread"), m.spread)
    m.last_trade_price = to_float(raw.get("lastTradePrice"), m.last_trade_price)
    m.volume = to_float(raw.get("volumeNum") or raw.get("volume"), m.volume)
    m.liquidity = to_float(raw.get("liquidityNum") or raw.get("liquidity"), m.liquidity)

    m.status = parse.status
    m.parse_status = parse.parse_status
    m.parse_notes = parse.parse_notes
    m.resolved_outcome = parse.resolved_outcome or m.resolved_outcome
    m.raw = raw
    m.last_updated = now_utc()


def _upsert_outcomes(db: Session, m: models.Market, parse: MarketParse) -> None:
    existing = {o.outcome_index: o for o in (m.outcomes_rel or [])}
    names = parse.outcomes or []
    tokens = parse.clob_token_ids or []
    for idx, name in enumerate(names):
        token = tokens[idx] if idx < len(tokens) else None
        o = existing.get(idx) or models.MarketOutcome(market_id=m.id, outcome_index=idx)
        o.outcome_name = name
        o.token_id = token
        if parse.resolved_outcome is not None:
            o.is_winner = name.strip().lower() == parse.resolved_outcome.strip().lower()
        if o.id is None:
            db.add(o)


def persist_markets(db: Session, pairs: list[tuple[dict, dict]]) -> dict:
    new = updated = 0
    by_asset: dict[str, int] = {}
    by_window: dict[int, int] = {}
    uncertain = 0
    now = now_utc()

    for raw, event in pairs:
        parse = parse_market(raw, event, now=now)
        cond = raw.get("conditionId")
        slug = raw.get("slug")
        m = None
        if cond:
            m = db.scalar(select(models.Market).where(models.Market.condition_id == cond))
        if m is None and slug:
            m = db.scalar(select(models.Market).where(models.Market.slug == slug))
        created = m is None
        if created:
            m = models.Market()
            db.add(m)
        _map_market_fields(m, raw, event, parse)
        db.flush()  # assign id
        _upsert_outcomes(db, m, parse)

        if created:
            new += 1
        else:
            updated += 1
        if parse.asset_symbol:
            by_asset[parse.asset_symbol] = by_asset.get(parse.asset_symbol, 0) + 1
        if parse.window_minutes:
            by_window[parse.window_minutes] = by_window.get(parse.window_minutes, 0) + 1
        if parse.parse_status == "uncertain":
            uncertain += 1

    return {
        "total": len(pairs),
        "new": new,
        "updated": updated,
        "uncertain": uncertain,
        "by_asset": by_asset,
        "by_window": by_window,
    }


async def run_discovery(
    *,
    include_closed: bool = True,
    max_pages_open: int = 10,
    max_pages_closed: int = 3,
    db: Session | None = None,
) -> dict:
    pairs = await fetch_crypto_updown(
        include_closed=include_closed,
        max_pages_open=max_pages_open,
        max_pages_closed=max_pages_closed,
    )
    # Always also grab the live/soon markets directly (paging never reaches the now-window).
    pairs += await fetch_current_window_pairs()
    if db is not None:
        summary = persist_markets(db, pairs)
        _record_last_run(summary, db=db)   # stamp + markets commit atomically
        db.commit()
    else:
        with session_scope() as s:
            summary = persist_markets(s, pairs)
            _record_last_run(summary, db=s)
    log.info("discovery_done", **{k: summary[k] for k in ("total", "new", "updated", "uncertain")})
    return summary


def _record_last_run(summary: dict, db: Session | None = None) -> None:
    def _write(s: Session) -> None:
        setting = s.get(models.AppSetting, "last_discovery_at")
        if setting is None:
            setting = models.AppSetting(key="last_discovery_at")
            s.add(setting)
        setting.value = {"at": now_utc().isoformat(), "summary": summary}
        setting.updated_at = now_utc()

    try:
        if db is not None:
            _write(db)
        else:
            with session_scope() as s:
                _write(s)
    except Exception as exc:  # pragma: no cover
        log.debug("record_last_run_failed", error=str(exc))


async def backfill_markets_for_wallet(
    address: str, *, max_markets: int = 2000, db: Session | None = None
) -> dict:
    """Discover exactly the markets a wallet traded (by slug), so PnL can be reconstructed.

    A wallet's trade history usually predates a rolling discovery window, so we fetch each
    traded market's event by slug from Gamma. Bounded by ``max_markets`` to respect the budget.
    """
    address = address.lower()
    with session_scope() as s:
        existing = {x for x in s.scalars(select(models.Market.slug)).all() if x}
        slugs = [
            x for x in s.scalars(
                select(models.Trade.slug).distinct().where(models.Trade.wallet_address == address)
            ).all()
            if x and x not in existing
        ]
    slugs = slugs[:max_markets]
    pairs: list[tuple[dict, dict]] = []
    client = GammaClient()
    try:
        for slug in slugs:
            try:
                events = await client.events_by_slug(slug)
            except Exception as exc:
                log.debug("backfill_slug_error", slug=slug, error=str(exc))
                continue
            for ev in events:
                for mk in ev.get("markets", []) or []:
                    if isinstance(mk, dict) and looks_like_crypto_updown(mk, ev):
                        pairs.append((mk, ev))
    finally:
        await client.aclose()

    if db is not None:
        summary = persist_markets(db, pairs)
        db.commit()
    else:
        with session_scope() as s:
            summary = persist_markets(s, pairs)
    log.info("backfill_done", requested=len(slugs), persisted=summary["total"])
    return {"requested": len(slugs), **summary}


def list_markets_for_universe(
    db: Session,
    *,
    statuses: list[str] | None = None,
    assets: list[str] | None = None,
    windows: list[int] | None = None,
) -> list[models.Market]:
    assets = [a.upper() for a in (assets or settings.assets)]
    windows = windows or settings.windows_minutes
    stmt = select(models.Market).where(models.Market.asset_symbol.in_(assets))
    if windows:
        stmt = stmt.where(models.Market.window_minutes.in_(windows))
    if statuses:
        stmt = stmt.where(models.Market.status.in_(statuses))
    return list(db.scalars(stmt.order_by(models.Market.start_time.desc())))
