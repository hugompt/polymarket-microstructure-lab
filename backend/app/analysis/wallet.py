"""Independent wallet analytics & skeptical PnL accounting.

This is the heart of the skeptical thesis. It NEVER trusts the Twitter claim or the API's
reported number on faith. It produces, clearly separated:

  * reported_realized_pnl   — what the Data API positions say (may be partial / a snapshot)
  * reconstructed_pnl       — independent cash-flow reconstruction from trades + resolutions
  * estimated_pnl_after_fees— reconstruction minus dynamically-estimated fees
  * portfolio_value         — current holdings worth (NOT profit)
  * total_volume / rewards  — separate again

Reconstruction is only as complete as our resolution coverage; coverage is reported honestly.
Break-even is computed dynamically per entry-price bucket (never hardcoded), and the observed
win rate is compared against it to show how thin (or negative) the real edge is.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import models
from ..util.normalize import BUCKET_ORDER, price_bucket
from .fees import FeeSchedule, breakeven_winrate, compute_fee_per_share, get_scenario
from . import metrics

# time-to-expiry / market-age buckets (seconds)
TTE_BUCKETS = [(0, 30, "0-30s"), (30, 60, "30-60s"), (60, 120, "60-120s"),
               (120, 300, "120-300s"), (300, 1e9, "300s+")]
AGE_BUCKETS = TTE_BUCKETS


def _bucket(value: float | None, buckets) -> str | None:
    if value is None:
        return None
    for lo, hi, label in buckets:
        if lo <= value < hi:
            return label
    return None


@dataclass
class TradeRow:
    trade: models.Trade
    market: models.Market | None
    won: bool | None
    pnl: float | None          # per-trade, BUY-held-to-resolution model, net of est fee
    gross_pnl: float | None
    fee: float
    resolved: bool


def _build_rows(db: Session, address: str, scenario: str) -> list[TradeRow]:
    sc = get_scenario(scenario)
    trades = list(db.scalars(
        select(models.Trade).where(models.Trade.wallet_address == address)
        .order_by(models.Trade.ts_utc.asc())
    ))
    market_cache: dict[int, models.Market] = {}
    rows: list[TradeRow] = []
    for t in trades:
        market = None
        if t.market_id:
            market = market_cache.get(t.market_id) or db.get(models.Market, t.market_id)
            if market:
                market_cache[t.market_id] = market
        resolved = bool(market and market.resolved_outcome)
        won = None
        pnl = gross = None
        fee = 0.0
        if resolved and t.side == "BUY" and t.price is not None and t.size is not None:
            won = (t.outcome or "").strip().lower() == market.resolved_outcome.strip().lower()
            schedule = FeeSchedule.from_market(market)
            fb = compute_fee_per_share(t.price, schedule, sc)
            fee = (fb.fee_win if won else fb.fee_lose) * t.size
            gross = t.size * ((1.0 - t.price) if won else (-t.price))
            pnl = gross - fee
        rows.append(TradeRow(trade=t, market=market, won=won, pnl=pnl, gross_pnl=gross,
                             fee=fee, resolved=resolved))
    return rows


def _market_level_reconstruction(rows: list[TradeRow]) -> tuple[float, float, int]:
    """Cash-flow reconstruction grouped by (condition, outcome): handles buys, sells, redemption.
    Returns (gross_pnl, est_fees, n_resolved_markets)."""
    by_market: dict[str, dict] = defaultdict(lambda: {"outcomes": defaultdict(lambda: {"buy_s": 0.0, "buy_c": 0.0, "sell_s": 0.0, "sell_c": 0.0}),
                                                       "winner": None, "schedule": None})
    for r in rows:
        if not r.resolved or not r.market or r.trade.price is None or r.trade.size is None:
            continue
        cid = r.market.condition_id or f"m{r.market.id}"
        g = by_market[cid]
        g["winner"] = (r.market.resolved_outcome or "").strip().lower()
        g["schedule"] = FeeSchedule.from_market(r.market)
        o = g["outcomes"][(r.trade.outcome or "").strip().lower()]
        notional = r.trade.price * r.trade.size
        if r.trade.side == "SELL":
            o["sell_s"] += r.trade.size
            o["sell_c"] += notional
        else:
            o["buy_s"] += r.trade.size
            o["buy_c"] += notional

    gross = 0.0
    fees = 0.0
    for cid, g in by_market.items():
        winner = g["winner"]
        for outcome, o in g["outcomes"].items():
            net_shares = o["buy_s"] - o["sell_s"]
            trading_cash = o["sell_c"] - o["buy_c"]
            redemption = net_shares * (1.0 if outcome == winner else 0.0)
            gross += trading_cash + redemption
            if outcome == winner and net_shares > 0 and g["schedule"]:
                # Fee on redeemed winnings (approx, conservative).
                # price proxy = avg buy price; fee on min(p,1-p) handled via per-share at 1.0 payout.
                fees += 0.0  # per-trade fees already summed in row model; kept 0 here to avoid double count
    return round(gross, 6), round(fees, 6), len(by_market)


def reported_pnl(db: Session, address: str) -> dict:
    closed = db.scalars(select(models.WalletClosedPosition).where(
        models.WalletClosedPosition.wallet_address == address)).all()
    open_pos = db.scalars(select(models.WalletPosition).where(
        models.WalletPosition.wallet_address == address)).all()
    realized = sum((p.realized_pnl or 0.0) for p in closed)
    realized_open = sum((p.realized_pnl or 0.0) for p in open_pos)
    cash = sum((p.cash_pnl or 0.0) for p in open_pos)
    return {
        "reported_realized_pnl_closed": round(realized, 4),
        "reported_realized_pnl_open": round(realized_open, 4),
        "reported_cash_pnl_open": round(cash, 4),
        "n_closed_positions": len(closed),
        "n_open_positions": len(open_pos),
    }


def analyze_wallet(db: Session, address: str, *, scenario: str = "conservative") -> dict:
    address = address.lower()
    rows = _build_rows(db, address, scenario)
    n_trades = len(rows)
    buy_resolved = [r for r in rows if r.pnl is not None]  # resolved BUY trades
    n_resolved = len(buy_resolved)

    pnls = [r.pnl for r in buy_resolved]
    gross_pnls = [r.gross_pnl for r in buy_resolved]
    wins = [bool(r.won) for r in buy_resolved]
    est_fees = sum(r.fee for r in buy_resolved)

    market_gross, _, n_resolved_markets = _market_level_reconstruction(rows)

    total_volume = sum((r.trade.notional or 0.0) for r in rows)
    portfolio_value = _portfolio_value(db, address)
    rewards = _rewards(db, address)
    reported = reported_pnl(db, address)

    reconstructed = round(sum(pnls) + est_fees, 6)  # gross (pre-fee) via per-trade model
    estimated_after_fees = round(sum(pnls), 6)      # net of estimated fees

    avg_entry = (sum(r.trade.price for r in buy_resolved if r.trade.price is not None) / n_resolved
                 if n_resolved else None)
    observed_wr = metrics.win_rate(wins)

    summary = metrics.summarize(pnls, wins)
    accounting = {
        "reported_realized_pnl": reported["reported_realized_pnl_closed"] + reported["reported_realized_pnl_open"],
        "reported_detail": reported,
        "reported_source": "data-api positions/closed_positions (snapshot; may be incomplete)",
        "reconstructed_pnl": reconstructed,
        "reconstructed_market_level": market_gross,
        "estimated_pnl_after_fees": estimated_after_fees,
        "estimated_fees": round(est_fees, 6),
        "portfolio_value": portfolio_value,
        "total_volume": round(total_volume, 4),
        "rewards": rewards,
        "fee_scenario": scenario,
    }
    coverage = {
        "n_trades": n_trades,
        "n_resolved_buy_trades": n_resolved,
        "n_resolved_markets": n_resolved_markets,
        "resolution_coverage_pct": round(100.0 * n_resolved / n_trades, 1) if n_trades else 0.0,
    }
    breakdowns = _breakdowns(buy_resolved, db, scenario)
    notes, warnings = _skeptic_notes(accounting, coverage, summary, avg_entry, observed_wr,
                                     breakdowns, scenario)

    return {
        "address": address,
        "profile": _profile(db, address),
        "accounting": accounting,
        "stats": {
            "n_trades": n_trades,
            "n_resolved_buy_trades": n_resolved,
            "win_rate": observed_wr,
            "profit_factor": summary["profit_factor"],
            "avg_win": summary["avg_win"],
            "avg_loss": summary["avg_loss"],
            "max_drawdown": summary["max_drawdown"],
            "sharpe_like": summary["sharpe_like"],
            "avg_entry_price": round(avg_entry, 4) if avg_entry else None,
            "is_low_sample": metrics.is_low_sample(n_resolved),
        },
        "coverage": coverage,
        "by_day": _by_day(buy_resolved),
        "breakdowns": breakdowns,
        "skeptic_notes": notes,
        "warnings": warnings,
    }


def _portfolio_value(db: Session, address: str) -> float:
    rows = db.scalars(select(models.WalletPosition.current_value).where(
        models.WalletPosition.wallet_address == address)).all()
    return round(sum(v or 0.0 for v in rows), 4)


def _rewards(db: Session, address: str):
    total = db.scalar(select(func.sum(models.WalletActivity.usdc_size)).where(
        models.WalletActivity.wallet_address == address,
        models.WalletActivity.type == "REWARD"))
    return round(total, 4) if total else None


def _profile(db: Session, address: str) -> dict:
    p = db.scalar(select(models.WalletProfile).where(models.WalletProfile.address == address))
    if not p:
        return {"name": None, "pseudonym": None}
    return {"name": p.name, "pseudonym": p.pseudonym, "bio": p.bio}


def _by_day(rows: list[TradeRow]) -> list[dict]:
    # Track gross AND after-fee per day so 'reconstructed_pnl' means the SAME thing (gross) as
    # accounting['reconstructed_pnl'], while the after-fee figures are explicitly named.
    by_day: dict[str, dict] = defaultdict(
        lambda: {"gross": 0.0, "net": 0.0, "volume": 0.0, "n": 0, "wins": 0})
    for r in rows:
        if r.trade.ts_utc is None:
            continue
        day = r.trade.ts_utc.strftime("%Y-%m-%d")
        d = by_day[day]
        d["gross"] += r.gross_pnl or 0.0
        d["net"] += r.pnl or 0.0
        d["volume"] += r.trade.notional or 0.0
        d["n"] += 1
        d["wins"] += 1 if r.won else 0
    out = []
    cum_gross = cum_net = 0.0
    for day in sorted(by_day):
        d = by_day[day]
        cum_gross += d["gross"]
        cum_net += d["net"]
        out.append({
            "day": day,
            "reconstructed_pnl": round(d["gross"], 4),              # GROSS (matches accounting)
            "estimated_pnl_after_fees": round(d["net"], 4),         # net of estimated fees
            "cumulative_pnl": round(cum_gross, 4),                  # GROSS cumulative
            "cumulative_pnl_after_fees": round(cum_net, 4),         # net cumulative
            "volume": round(d["volume"], 2), "n": d["n"],
            "win_rate": round(d["wins"] / d["n"], 4) if d["n"] else None,
        })
    return out


def _breakdowns(rows: list[TradeRow], db: Session, scenario: str) -> dict:
    def rec(r: TradeRow) -> dict:
        t = r.trade
        ts = t.ts_utc
        return {
            "pnl": r.pnl or 0.0, "won": r.won, "volume": t.notional or 0.0,
            "asset": (r.market.asset_symbol if r.market else None),
            "hour": ts.hour if ts else None,
            "weekday": ("weekend" if ts and ts.weekday() >= 5 else "weekday") if ts else None,
            "window": (r.market.window_minutes if r.market else None),
            "bucket": price_bucket(t.price),
            "price": t.price,
            "tte": _tte(r), "age": _age(r),
        }
    recs = [rec(r) for r in rows]

    def grp(key):
        return metrics.group_breakdown(recs, lambda x: x.get(key),
                                        volume_fn=lambda x: x.get("volume") or 0.0)

    # break-even vs actual per entry bucket (dynamic, never hardcoded)
    sc = get_scenario(scenario)
    by_bucket_rows: dict[str, list[dict]] = defaultdict(list)
    for x in recs:
        if x["bucket"]:
            by_bucket_rows[x["bucket"]].append(x)
    breakeven_by_bucket = []
    for b in BUCKET_ORDER:
        items = by_bucket_rows.get(b, [])
        if not items:
            continue
        prices = [i["price"] for i in items if i["price"] is not None]
        avg_entry = sum(prices) / len(prices) if prices else None
        wins = [bool(i["won"]) for i in items if i["won"] is not None]
        actual_wr = metrics.win_rate(wins)
        be = breakeven_winrate(avg_entry, FeeSchedule.from_market(None), sc) if avg_entry else None
        edge = (actual_wr - be) if (actual_wr is not None and be is not None) else None
        breakeven_by_bucket.append({
            "bucket": b, "n": len(items),
            "avg_entry": round(avg_entry, 4) if avg_entry else None,
            "breakeven_winrate": round(be, 4) if be else None,
            "actual_win_rate": round(actual_wr, 4) if actual_wr is not None else None,
            "edge": round(edge, 4) if edge is not None else None,
            "is_low_sample": metrics.is_low_sample(len(items)),
        })

    entry_dist = metrics.histogram(
        [x["price"] for x in recs if x["price"] is not None],
        [(0, 0.05, "0-5"), (0.05, 0.15, "5-15"), (0.15, 0.35, "15-35"), (0.35, 0.5, "35-50"),
         (0.5, 0.65, "50-65"), (0.65, 0.85, "65-85"), (0.85, 0.95, "85-95"), (0.95, 1.0001, "95-100")],
    )

    return {
        "by_asset": grp("asset"),
        "by_hour": grp("hour"),
        "by_weekday_weekend": grp("weekday"),
        "by_window": grp("window"),
        "by_entry_bucket": grp("bucket"),
        "by_time_to_expiry": grp("tte"),
        "by_market_age": grp("age"),
        "entry_price_distribution": entry_dist,
        "breakeven_by_bucket": breakeven_by_bucket,
    }


def _tte(r: TradeRow) -> str | None:
    enr = r.trade.enrichment
    if enr and enr.seconds_until_close is not None:
        return _bucket(enr.seconds_until_close, TTE_BUCKETS)
    if r.market and r.market.end_time and r.trade.ts_utc:
        return _bucket((r.market.end_time - r.trade.ts_utc).total_seconds(), TTE_BUCKETS)
    return None


def _age(r: TradeRow) -> str | None:
    enr = r.trade.enrichment
    if enr and enr.seconds_since_open is not None:
        return _bucket(enr.seconds_since_open, AGE_BUCKETS)
    if r.market and r.market.start_time and r.trade.ts_utc:
        return _bucket((r.trade.ts_utc - r.market.start_time).total_seconds(), AGE_BUCKETS)
    return None


def _skeptic_notes(accounting, coverage, summary, avg_entry, observed_wr, breakdowns, scenario):
    notes: list[str] = []
    warnings: list[str] = []
    n = coverage["n_resolved_buy_trades"]

    notes.append(
        f"The X/Twitter claim of ~$21k-$24k PnL is treated as an UNVERIFIED hypothesis. "
        f"Independently reconstructed PnL over the {coverage['n_resolved_markets']} resolved "
        f"markets we have data for is ${accounting['reconstructed_pnl']:.2f} gross / "
        f"${accounting['estimated_pnl_after_fees']:.2f} after estimated fees ({scenario} scenario)."
    )
    if coverage["resolution_coverage_pct"] < 90 and coverage["n_trades"]:
        warnings.append(
            f"Resolution coverage is only {coverage['resolution_coverage_pct']:.0f}% "
            f"({n}/{coverage['n_trades']} trades). Reconstructed PnL is a LOWER-completeness "
            f"estimate — run discovery over more history to raise coverage."
        )
    rep = accounting["reported_realized_pnl"]
    rec = accounting["reconstructed_pnl"]
    if abs(rep) > 1e-6 or abs(rec) > 1e-6:
        notes.append(
            f"Reported realized PnL (${rep:.2f}, from the Data API snapshot) vs reconstructed "
            f"(${rec:.2f}) differ by ${rep - rec:.2f}. Causes can include rewards/rebates, gas, "
            f"unresolved markets, sells, or our coverage gap — different accounting methods, not proof."
        )
    if avg_entry is not None and observed_wr is not None:
        naive_be = avg_entry * 100
        notes.append(
            f"Average entry price ${avg_entry:.3f} implies a naive break-even win rate of "
            f"~{naive_be:.1f}% (before fees). Observed win rate is {observed_wr*100:.1f}%. "
            f"The directional 'edge' is ~{(observed_wr - avg_entry)*100:.1f} pts and is highly "
            f"sensitive to fees, spread and fill quality — exactly where infra/latency, not "
            f"BTC-direction prediction, would matter."
        )
    notes.append(
        f"Portfolio value (${accounting['portfolio_value']:.2f}) is NOT profit — it is the current "
        f"mark-to-market of open holdings."
    )
    # Buckets where the bot is actually losing relative to break-even.
    losing = [b for b in breakdowns["breakeven_by_bucket"]
              if b.get("edge") is not None and b["edge"] < 0 and not b["is_low_sample"]]
    if losing:
        worst = min(losing, key=lambda b: b["edge"])
        notes.append(
            f"In the {worst['bucket']}c entry bucket (n={worst['n']}) the actual win rate "
            f"({worst['actual_win_rate']*100:.1f}%) is BELOW the break-even rate "
            f"({worst['breakeven_winrate']*100:.1f}%) — a negative-edge zone."
        )
    if summary["is_low_sample"]:
        warnings.append(
            f"Only {n} resolved trades available — below the {metrics.LOW_SAMPLE_THRESHOLD}-trade "
            f"threshold. Treat all win-rate / PnL figures as NOT statistically meaningful yet."
        )
    if not accounting.get("rewards"):
        warnings.append("No reward/rebate activity captured; CLOB liquidity rewards (if any) are not in this PnL.")
    return notes, warnings
