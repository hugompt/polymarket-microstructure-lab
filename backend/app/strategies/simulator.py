"""Backtest simulator.

For each in-scope resolved market it builds a MarketContext, asks the strategy for entry
intents, then prices/fills/fees/resolves each intent under the chosen latency + fill model +
fee scenario. Honest about data quality:

  * Price fidelity is tracked (high = live book, med = wallet print, low = last-trade / 0.5
    open assumption) and surfaced so thin-data backtests are never mistaken for clean ones.
  * Markets a strategy can't act on (missing ticks/book/wallet data) are counted as skipped
    with the reason, never silently dropped.
  * Every run is compared to the random baseline, and low sample sizes raise a warning.

Nothing here trades. It reads recorded data and writes simulated results only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis import metrics
from ..analysis.fees import FeeSchedule, compute_fee_per_share, get_scenario
from ..config import settings
from ..db import models
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..util.normalize import price_bucket
from ..util.timeutil import now_utc
from .base import MarketContext
from .registry import get_strategy

log = get_logger("strategies.simulator")

# fill model -> (order_type, pessimism)
FILL_MODELS = {
    "taker": ("taker", "realistic"),
    "maker": ("maker", "realistic"),
    "optimistic": ("taker", "optimistic"),
    "realistic": ("taker", "realistic"),
    "conservative": ("taker", "conservative"),
}


@dataclass
class FillResult:
    filled: bool
    fill_price: float | None
    fill_size: float
    price_source: str
    fidelity: str
    spread_cost: float
    slippage: float
    reason_unfilled: str | None = None
    partial: bool = False  # True when depth capped the fill below the requested size


def load_scope_markets(
    db: Session, *, assets, windows, date_from, date_to, limit: int = 5000
) -> list[models.Market]:
    stmt = select(models.Market).where(models.Market.resolved_outcome.is_not(None))
    if assets:
        stmt = stmt.where(models.Market.asset_symbol.in_([a.upper() for a in assets]))
    if windows:
        stmt = stmt.where(models.Market.window_minutes.in_(windows))
    if date_from:
        stmt = stmt.where(models.Market.start_time >= date_from)
    if date_to:
        stmt = stmt.where(models.Market.start_time <= date_to)
    return list(db.scalars(stmt.order_by(models.Market.start_time.asc()).limit(limit)))


def build_context(db: Session, market: models.Market, wallet: str | None) -> MarketContext:
    token_by_outcome: dict[str, str] = {}
    for o in market.outcomes_rel or []:
        if o.outcome_name and o.token_id:
            token_by_outcome[o.outcome_name] = o.token_id
    if not token_by_outcome and market.up_token_id:
        token_by_outcome = {"Up": market.up_token_id, "Down": market.down_token_id}

    books_by_token: dict[str, list[models.OrderbookSnapshot]] = {}
    for tok in token_by_outcome.values():
        rows = list(db.scalars(
            select(models.OrderbookSnapshot)
            .where(models.OrderbookSnapshot.token_id == tok,
                   models.OrderbookSnapshot.accepted.is_(True))
            .order_by(models.OrderbookSnapshot.received_ts.asc())
        ))
        if rows:
            books_by_token[tok] = rows

    ticks_by_source: dict[str, list[models.CryptoPriceTick]] = {}
    if market.asset_symbol and market.start_time and market.end_time:
        lo = market.start_time - timedelta(seconds=120)
        for src in ("binance", "chainlink", "rtds"):
            rows = list(db.scalars(
                select(models.CryptoPriceTick)
                .where(models.CryptoPriceTick.asset_symbol == market.asset_symbol,
                       models.CryptoPriceTick.source == src,
                       models.CryptoPriceTick.received_ts >= lo,
                       models.CryptoPriceTick.received_ts <= market.end_time,
                       models.CryptoPriceTick.accepted.is_(True))
                .order_by(models.CryptoPriceTick.received_ts.asc())
            ))
            if rows:
                ticks_by_source[src] = rows

    wallet_trades: list[models.Trade] = []
    if wallet:
        wallet_trades = list(db.scalars(
            select(models.Trade).where(models.Trade.market_id == market.id,
                                       models.Trade.wallet_address == wallet.lower())
            .order_by(models.Trade.ts_utc.asc())
        ))
    return MarketContext(market=market, token_by_outcome=token_by_outcome,
                         books_by_token=books_by_token, ticks_by_source=ticks_by_source,
                         wallet_trades=wallet_trades)


def _wallet_price_near(ctx: MarketContext, token: str, at: datetime | None) -> float | None:
    best = None
    best_dt = None
    for tr in ctx.wallet_trades:
        if tr.asset == token and tr.price is not None and tr.ts_utc is not None and at is not None:
            dt = abs((tr.ts_utc - at).total_seconds())
            if best_dt is None or dt < best_dt:
                best_dt, best = dt, tr.price
    return best


def simulate_fill(ctx: MarketContext, token: str, at: datetime | None, size: float, *,
                  fill_model: str, won: bool, schedule: FeeSchedule, scenario) -> FillResult:
    order_type, pessimism = FILL_MODELS.get(fill_model, ("taker", "realistic"))
    book = ctx.book_at(token, at) if token else None

    # 1) Live book.
    if book and (book.best_ask is not None or book.best_bid is not None):
        if pessimism == "conservative" and (book.is_stale or not book.accepted):
            return FillResult(False, None, 0.0, "book", "high", 0.0, 0.0, "rejected_bad_data")
        mid = book.mid
        if order_type == "maker" and book.best_bid is not None:
            intended = book.best_bid
            filled = _maker_would_fill(ctx, token, intended, at, pessimism)
            if not filled:
                return FillResult(False, intended, 0.0, "book_bid", "high", 0.0, 0.0, "missed_fill")
            # Resting at the bid (below mid) is a SAVING vs mid -> negative spread_cost, mirroring
            # the taker convention where crossing to the ask (above mid) is a positive cost.
            return FillResult(True, intended, size, "book_bid", "high",
                              spread_cost=(intended - mid) if mid else 0.0, slippage=0.0)
        # taker
        if book.best_ask is not None:
            price = book.best_ask
            slip = _taker_slippage(book, size, pessimism)
            price = min(0.999, price + slip)
            fill_size, was_partial = _partial(book, size)
            return FillResult(True, price, fill_size, "book_ask", "high",
                              spread_cost=max(0.0, price - mid) if mid else 0.0,
                              slippage=slip, reason_unfilled=None, partial=was_partial)

    # 2) Wallet print near t (medium fidelity).
    wp = _wallet_price_near(ctx, token, at)
    if wp is not None:
        slip = 0.0 if pessimism == "optimistic" else (ctx.market.tick_size or 0.01)
        return FillResult(True, min(0.999, wp + slip), size, "wallet_print", "med", 0.0, slip)

    # 3) Market last trade price (low).
    if ctx.market.last_trade_price is not None:
        return FillResult(True, ctx.market.last_trade_price, size, "last_trade", "low", 0.0, 0.0)

    # 4) Open assumption 0.5 (lowest; only sensible near open).
    return FillResult(True, 0.5, size, "open_0.5", "low", 0.0, 0.0)


def _maker_would_fill(ctx, token, bid_price, at, pessimism) -> bool:
    """Infer post-only fill: did the book later trade through our resting bid within the window?"""
    if pessimism == "optimistic":
        return True
    books = ctx.books_by_token.get(token) or []
    later = [b for b in books if b.received_ts and at and b.received_ts > at]
    if not later:
        return pessimism != "conservative"  # no evidence: realistic assumes fill, conservative doesn't
    # Filled if some later best_ask <= our bid (price came to us) or last trade <= bid.
    for b in later:
        if b.best_ask is not None and b.best_ask <= bid_price:
            return True
        if b.last_trade_price is not None and b.last_trade_price <= bid_price:
            return True
    return False


def _taker_slippage(book, size, pessimism) -> float:
    if pessimism == "optimistic":
        return 0.0
    base = 0.0
    depth = (book.ask_depth_top5 or 0.0)
    if depth and size > depth:
        base += 0.01  # walked beyond top-5
    if pessimism == "conservative":
        base += 0.005  # extra half-cent pessimism
    return base


def _partial(book, size) -> tuple[float, bool]:
    depth = book.ask_depth_top10 or book.ask_depth_top5
    if depth and size > depth > 0:
        return float(depth), True
    return float(size), False


def run_strategy_over_markets(
    db: Session, strategy_key: str, markets: list[models.Market], *,
    latency_ms: int, fill_model: str, fee_scenario: str, size: float,
    params: dict | None, wallet: str | None, seed: int | None = None,
) -> dict:
    strat = get_strategy(strategy_key, {**(params or {}), "size": size}, seed=seed)
    sc = get_scenario(fee_scenario)
    trades: list[dict] = []
    skipped: dict[str, int] = {}
    n_attempts = n_filled = n_markets_acted = 0

    for market in markets:
        ctx = build_context(db, market, wallet)
        missing = strat.missing_requirements(ctx)
        if missing:
            for r in missing:
                skipped[r] = skipped.get(r, 0) + 1
            continue
        intents = strat.generate(ctx)
        if not intents:
            skipped["no_signal"] = skipped.get("no_signal", 0) + 1
            continue
        n_markets_acted += 1
        schedule = FeeSchedule.from_market(market)
        for intent in intents:
            n_attempts += 1
            token = ctx.token_by_outcome.get(intent.outcome)
            t_intended = market.start_time + timedelta(seconds=intent.offset_seconds) if market.start_time else None
            t_fill = (t_intended + timedelta(milliseconds=latency_ms)) if t_intended else None
            won = (intent.outcome == market.resolved_outcome)
            fr = simulate_fill(ctx, token, t_fill, intent.size, fill_model=fill_model,
                               won=won, schedule=schedule, scenario=sc)
            if not fr.filled:
                trades.append(_trade_row(market, intent, t_intended, None, fr, won, 0.0, 0.0))
                continue
            n_filled += 1
            fb = compute_fee_per_share(fr.fill_price, schedule, sc)
            fee = (fb.fee_win if won else fb.fee_lose) * fr.fill_size
            pnl = fr.fill_size * ((1.0 - fr.fill_price) if won else (-fr.fill_price)) - fee
            trades.append(_trade_row(market, intent, t_intended, t_fill, fr, won, fee, pnl))

    return {
        "trades": trades, "skipped": skipped,
        "n_markets": len(markets), "n_markets_acted": n_markets_acted,
        "n_attempts": n_attempts, "n_filled": n_filled,
    }


def _trade_row(market, intent, t_intended, t_fill, fr: FillResult, won, fee, pnl) -> dict:
    ts = t_intended
    return {
        "market_id": market.id, "asset_symbol": market.asset_symbol,
        "window_minutes": market.window_minutes, "outcome_chosen": intent.outcome,
        "intended_ts": t_intended, "intended_price": fr.fill_price if fr.filled else None,
        "filled": fr.filled, "fill_price": fr.fill_price if fr.filled else None,
        "fill_ts": t_fill if fr.filled else None, "size": fr.fill_size if fr.filled else intent.size,
        "fees": round(fee, 6), "spread_cost": round(fr.spread_cost, 6), "slippage": round(fr.slippage, 6),
        "resolved_outcome": market.resolved_outcome, "won": won if fr.filled else None,
        "pnl": round(pnl, 6) if fr.filled else 0.0,
        "hour_utc": ts.hour if ts else None,
        "is_weekend": (ts.weekday() >= 5) if ts else None,
        "entry_price_bucket": price_bucket(fr.fill_price) if fr.filled else None,
        # Keep the partial marker even on filled rows (don't silently mask a capped fill).
        "reason_unfilled": ("partial_fill" if fr.partial else None) if fr.filled else fr.reason_unfilled,
        "raw": {"price_source": fr.price_source, "fidelity": fr.fidelity, "reason": intent.reason,
                "partial": fr.partial, "intended_size": intent.size},
    }


def compute_run_metrics(result: dict, *, random_net: float | None = None) -> dict:
    filled = [t for t in result["trades"] if t["filled"]]
    pnls = [t["pnl"] for t in filled]
    wins = [bool(t["won"]) for t in filled if t["won"] is not None]
    entries = [t["fill_price"] for t in filled if t["fill_price"] is not None]
    fees = sum(t["fees"] for t in filled)
    gross = sum(pnls) + fees
    summ = metrics.summarize(pnls, wins)
    fidelity = {"high": 0, "med": 0, "low": 0}
    for t in filled:
        fidelity[t["raw"]["fidelity"]] = fidelity.get(t["raw"]["fidelity"], 0) + 1
    n_filled = len(filled)
    # Partial fills: count them and report a size-weighted fill rate so depth-capped fills are
    # never counted as full fills (capacity is never overstated).
    n_partial = sum(1 for t in filled if t["raw"].get("partial"))
    intended_size = sum((t["raw"].get("intended_size") or 0.0) for t in result["trades"])
    filled_size = sum((t["size"] or 0.0) for t in filled)
    out = {
        "n_markets": result["n_markets"], "n_markets_acted": result["n_markets_acted"],
        "n_attempts": result["n_attempts"], "n_filled": n_filled,
        "n_partial_fills": n_partial,
        "fill_rate": round(n_filled / result["n_attempts"], 4) if result["n_attempts"] else None,
        "notional_fill_rate": round(filled_size / intended_size, 4) if intended_size else None,
        "win_rate": summ["win_rate"],
        "avg_entry_price": round(sum(entries) / len(entries), 4) if entries else None,
        "avg_exit_value": round(sum(1.0 if t["won"] else 0.0 for t in filled) / n_filled, 4) if n_filled else None,
        "gross_pnl": round(gross, 4), "net_pnl": round(sum(pnls), 4),
        "est_fees": round(fees, 4),
        "max_drawdown": summ["max_drawdown"], "profit_factor": summ["profit_factor"],
        "sharpe_like": summ["sharpe_like"],
        "skipped": result["skipped"], "price_fidelity": fidelity,
        "is_low_sample": metrics.is_low_sample(n_filled),
        "breakdowns": _breakdowns(filled),
    }
    if random_net is not None:
        out["vs_random_net_pnl"] = round(out["net_pnl"] - random_net, 4)
    return out


def _breakdowns(filled: list[dict]) -> dict:
    def grp(key):
        return metrics.group_breakdown(filled, lambda x: x.get(key),
                                        volume_fn=lambda x: (x.get("fill_price") or 0) * (x.get("size") or 0))
    return {
        "by_asset": grp("asset_symbol"),
        "by_hour": grp("hour_utc"),
        "by_weekend": grp("is_weekend"),
        "by_window": grp("window_minutes"),
        "by_entry_bucket": grp("entry_price_bucket"),
    }


def run_backtest(
    strategy_key: str, *,
    assets: list[str] | None = None, windows: list[int] | None = None,
    date_from: datetime | None = None, date_to: datetime | None = None,
    latency_ms: int = 100, fill_model: str = "realistic", fee_scenario: str = "conservative",
    size: float = 100.0, params: dict | None = None, wallet: str | None = None,
    compare_random: bool = True, persist: bool = True, limit: int = 5000,
    db: Session | None = None, seed: int = 1234,
) -> dict:
    wallet = wallet or settings.target_wallet

    def _run(s: Session) -> dict:
        markets = load_scope_markets(s, assets=assets, windows=windows,
                                     date_from=date_from, date_to=date_to, limit=limit)
        result = run_strategy_over_markets(
            s, strategy_key, markets, latency_ms=latency_ms, fill_model=fill_model,
            fee_scenario=fee_scenario, size=size, params=params, wallet=wallet, seed=seed)

        random_net = None
        random_metrics = None
        if compare_random and strategy_key != "random":
            rand = run_strategy_over_markets(
                s, "random", markets, latency_ms=latency_ms, fill_model=fill_model,
                fee_scenario=fee_scenario, size=size, params=None, wallet=wallet, seed=seed)
            random_metrics = compute_run_metrics(rand)
            random_net = random_metrics["net_pnl"]

        m = compute_run_metrics(result, random_net=random_net)
        warnings = _warnings(m, strategy_key)
        out = {
            "strategy_key": strategy_key, "metrics": m, "vs_random": random_metrics,
            "warnings": warnings, "trades": result["trades"],
            "params": {"assets": assets, "windows": windows, "latency_ms": latency_ms,
                       "fill_model": fill_model, "fee_scenario": fee_scenario, "size": size,
                       **(params or {})},
        }
        if persist:
            out["run_id"] = _persist(s, out, assets, windows, date_from, date_to,
                                     latency_ms, fill_model, fee_scenario)
            s.commit()
        return out

    if db is not None:
        return _run(db)
    with session_scope() as s:
        return _run(s)


def _warnings(m: dict, strategy_key: str) -> list[str]:
    w = []
    if m["is_low_sample"]:
        w.append(f"Only {m['n_filled']} filled trades (< {metrics.LOW_SAMPLE_THRESHOLD}). "
                 "Results are NOT statistically meaningful.")
    fid = m["price_fidelity"]
    low = fid.get("low", 0)
    total = sum(fid.values()) or 1
    if low / total > 0.5:
        w.append(f"{low}/{total} fills used LOW-fidelity prices (no live orderbook). "
                 "Run the collector to record real book data for trustworthy backtests.")
    if m["skipped"]:
        w.append("Skipped markets by reason: " + ", ".join(f"{k}={v}" for k, v in m["skipped"].items()))
    return w


def _persist(s, out, assets, windows, date_from, date_to, latency_ms, fill_model, fee_scenario) -> int:
    m = out["metrics"]
    run = models.StrategyRun(
        strategy_key=out["strategy_key"], label=f"{out['strategy_key']} {fill_model}/{fee_scenario}",
        params=out["params"], assets=assets, windows=windows, date_from=date_from, date_to=date_to,
        latency_ms=latency_ms, fill_model=fill_model, fee_scenario=fee_scenario, status="done",
        n_markets=m["n_markets"], n_attempts=m["n_attempts"], n_filled=m["n_filled"],
    )
    s.add(run)
    s.flush()
    for t in out["trades"]:
        s.add(models.StrategyRunTrade(run_id=run.id, **{k: t[k] for k in (
            "market_id", "asset_symbol", "window_minutes", "outcome_chosen", "intended_ts",
            "intended_price", "filled", "fill_price", "fill_ts", "size", "fees", "spread_cost",
            "slippage", "resolved_outcome", "won", "pnl", "hour_utc", "is_weekend",
            "entry_price_bucket", "reason_unfilled", "raw")}))
    s.add(models.StrategyRunMetric(
        run_id=run.id, n_markets=m["n_markets"], n_attempts=m["n_attempts"], n_filled=m["n_filled"],
        fill_rate=m["fill_rate"], win_rate=m["win_rate"], avg_entry_price=m["avg_entry_price"],
        avg_exit_value=m["avg_exit_value"], gross_pnl=m["gross_pnl"], net_pnl=m["net_pnl"],
        max_drawdown=m["max_drawdown"], profit_factor=m["profit_factor"], sharpe_like=m["sharpe_like"],
        vs_random_net_pnl=m.get("vs_random_net_pnl"), sample_warning=m["is_low_sample"],
        breakdowns=m["breakdowns"],
        full={**m, "vs_random": out.get("vs_random"), "warnings": out.get("warnings"),
              "params": out.get("params")},
    ))
    return run.id
