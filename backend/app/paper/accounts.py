"""Pure latency-account fill & settlement logic (no IO -> unit-testable).

The single most important realism here is the LATENCY effect: a decision is made observing the
book at ``decision_ts`` (you would pay ``decision_price`` = best ask at that instant if latency
were zero). The order only "arrives" at ``decision_ts + latency``, and is filled against the book
AS IT IS THEN — which may have moved against you while the order was in flight. The realised
``slippage_vs_decision`` (fill price minus decision price) is exactly the cost of latency, and
differs across latency accounts fed the same decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..analysis.fees import FeeSchedule, compute_fee_per_share, get_scenario


@dataclass
class LiveBook:
    token_id: str
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    bid_depth: float | None = None
    ask_depth: float | None = None
    ts: datetime | None = None


@dataclass
class Decision:
    decision_id: str
    market_id: int | None
    condition_id: str | None
    asset: str | None
    window_minutes: int | None
    outcome: str               # "Up" | "Down"
    token_id: str | None
    decision_ts: datetime
    decision_book: LiveBook    # book observed when the decision was made
    size: float
    reason: str = ""


@dataclass
class PaperOrderState:
    decision: Decision
    latency_ms: int
    arrive_ts: datetime
    status: str = "open"       # open | filled | missed | settled | expired
    fill_price: float | None = None
    fill_size: float = 0.0
    fees: float = 0.0
    spread_cost: float = 0.0
    slippage_vs_decision: float | None = None
    resolved_outcome: str | None = None
    won: bool | None = None
    pnl: float | None = None
    settle_ts: datetime | None = None
    reason: str | None = None
    raw: dict = field(default_factory=dict)


def make_orders(decision: Decision, latency_grid_ms: list[int]) -> list[PaperOrderState]:
    """Fan a single decision out into one open order per latency account."""
    orders = []
    for lat in latency_grid_ms:
        orders.append(PaperOrderState(
            decision=decision, latency_ms=lat,
            arrive_ts=decision.decision_ts + timedelta(milliseconds=lat),
        ))
    return orders


def fill_order(
    order: PaperOrderState,
    book_at_arrive: LiveBook | None,
    *,
    schedule: FeeSchedule,
    fee_scenario: str = "conservative",
    max_slippage: float | None = None,
) -> PaperOrderState:
    """Taker fill at the CURRENT (post-latency) best ask. Records the latency cost vs decision.

    ``book_at_arrive`` is the live book at (or just after) the order's arrival time. If there is
    no ask (no liquidity) the order is marked missed. ``max_slippage`` optionally rejects fills
    where the price ran away beyond a tolerance during the latency window (a real bot would often
    cancel-on-adverse-move)."""
    if order.status != "open":
        return order
    sc = get_scenario(fee_scenario)
    decision_ask = order.decision.decision_book.best_ask

    if book_at_arrive is None or book_at_arrive.best_ask is None:
        order.status = "missed"
        order.reason = "no_liquidity_at_arrival"
        return order

    ask = book_at_arrive.best_ask
    if decision_ask is not None and max_slippage is not None and (ask - decision_ask) > max_slippage:
        order.status = "missed"
        order.reason = "adverse_move_exceeds_tolerance"
        order.slippage_vs_decision = round(ask - decision_ask, 6)
        return order

    order.fill_price = ask
    order.fill_size = order.decision.size
    order.slippage_vs_decision = round(ask - decision_ask, 6) if decision_ask is not None else None
    order.spread_cost = round(max(0.0, ask - book_at_arrive.mid), 6) if book_at_arrive.mid else 0.0
    fb = compute_fee_per_share(ask, schedule, sc)
    # Fee depends on win/lose; store both possibilities' per-share and resolve at settlement.
    order.raw["fee_win_per_share"] = fb.fee_win
    order.raw["fee_lose_per_share"] = fb.fee_lose
    order.status = "filled"
    order.reason = None
    return order


def settle_order(order: PaperOrderState, resolved_outcome: str, settle_ts: datetime) -> PaperOrderState:
    """Settle a filled order against the REAL resolution -> realised paper PnL."""
    if order.status != "filled":
        return order
    won = (order.decision.outcome or "").strip().lower() == (resolved_outcome or "").strip().lower()
    fee_per_share = order.raw.get("fee_win_per_share", 0.0) if won else order.raw.get("fee_lose_per_share", 0.0)
    fee = fee_per_share * order.fill_size
    payoff = (1.0 - order.fill_price) if won else (-order.fill_price)
    order.fees = round(fee, 6)
    order.won = won
    order.pnl = round(order.fill_size * payoff - fee, 6)
    order.resolved_outcome = resolved_outcome
    order.settle_ts = settle_ts
    order.status = "settled"
    return order


def account_summary(orders: list[PaperOrderState], latency_ms: int) -> dict:
    """Aggregate one latency account's orders into a summary row."""
    mine = [o for o in orders if o.latency_ms == latency_ms]
    filled = [o for o in mine if o.status in ("filled", "settled")]
    settled = [o for o in mine if o.status == "settled"]
    missed = [o for o in mine if o.status == "missed"]
    pnls = [o.pnl for o in settled if o.pnl is not None]
    wins = [o for o in settled if o.won]
    fees = sum(o.fees for o in settled)
    slips = [o.slippage_vs_decision for o in mine if o.slippage_vs_decision is not None]
    realized = round(sum(pnls), 4) if pnls else 0.0
    return {
        "latency_ms": latency_ms,
        "n_decisions": len(mine),
        "n_filled": len(filled),
        "n_missed": len(missed),
        "n_settled": len(settled),
        "n_won": len(wins),
        "win_rate": round(len(wins) / len(settled), 4) if settled else None,
        "realized_pnl": realized,
        "fees_paid": round(fees, 4),
        "avg_slippage_vs_decision": round(sum(slips) / len(slips), 6) if slips else 0.0,
        "fill_rate": round(len(filled) / len(mine), 4) if mine else None,
    }
