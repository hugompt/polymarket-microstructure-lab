"""Fee, slippage & break-even engine.

Core idea (rule 12): break-even win rate is NEVER hardcoded. For a binary Up/Down share
bought at effective price ``f`` (pays $1 on win, $0 on loss):

    EV per share (win prob w) = (w - f) - expected_fee_per_share
    naive break-even          = f                       (zero fees)
    fee-inclusive break-even  = (f + fee_lose) / (1 - fee_win + fee_lose)   [per share]

So buying at $0.97 needs a ~97 %+ hit rate before fees even enter — the engine surfaces that
dynamically per trade and per entry-price bucket.

Fee model: Polymarket binary fees are charged proportional to the "riskier" side
``min(p, 1-p)`` (small near price extremes). The market's own ``feeSchedule`` is used when
present; otherwise configurable fallbacks + sensitivity scenarios (maker / taker /
conservative) are run, and a warning is attached so estimates are never mistaken for facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from ..util.normalize import to_float


@dataclass(frozen=True)
class FeeScenario:
    key: str
    is_maker: bool
    override_rate: float | None = None  # if set, ignore market schedule rate
    note: str = ""


# Sensitivity scenarios used when maker/taker is unknown.
MAKER_LIKE = FeeScenario("maker_like", is_maker=True, note="assume passive maker (rebate-eligible)")
TAKER_LIKE = FeeScenario("taker_like", is_maker=False, note="assume aggressive taker (full fee)")
CONSERVATIVE = FeeScenario(
    "conservative", is_maker=False, override_rate=None,
    note="taker fee + worst-case rounding; pessimistic",
)
NONE = FeeScenario("none", is_maker=False, override_rate=0.0, note="zero-fee idealisation")

SCENARIOS = {s.key: s for s in (MAKER_LIKE, TAKER_LIKE, CONSERVATIVE, NONE)}


def get_scenario(key: str | None) -> FeeScenario:
    return SCENARIOS.get((key or "conservative").lower(), CONSERVATIVE)


@dataclass
class FeeSchedule:
    rate: float
    exponent: float = 1.0
    taker_only: bool = True
    rebate_rate: float = 0.0
    present: bool = False          # True if sourced from market metadata
    source: str = "fallback"

    @classmethod
    def from_market(cls, market) -> "FeeSchedule":
        """Build from a Market ORM object or a raw Gamma dict; fall back to settings."""
        sched = None
        if market is not None:
            sched = getattr(market, "fee_schedule", None)
            if sched is None and isinstance(market, dict):
                sched = market.get("feeSchedule") or market.get("fee_schedule")
        if isinstance(sched, dict) and sched:
            return cls(
                rate=to_float(sched.get("rate"), settings.fallback_fee_rate) or 0.0,
                exponent=to_float(sched.get("exponent"), 1.0) or 1.0,
                taker_only=bool(sched.get("takerOnly", sched.get("taker_only", True))),
                rebate_rate=to_float(sched.get("rebateRate", sched.get("rebate_rate")), 0.0) or 0.0,
                present=True,
                source="market",
            )
        return cls(rate=settings.fallback_fee_rate, present=False, source="fallback")


@dataclass
class FeeBreakdown:
    fee_win: float          # fee paid (per share) if the position WINS
    fee_lose: float         # fee paid (per share) if the position LOSES
    effective_rate: float
    schedule_present: bool
    warnings: list[str] = field(default_factory=list)


def _min_side(price: float) -> float:
    p = max(0.0, min(1.0, price))
    return min(p, 1.0 - p)


def compute_fee_per_share(price: float, schedule: FeeSchedule, scenario: FeeScenario) -> FeeBreakdown:
    warnings: list[str] = []
    rate = scenario.override_rate if scenario.override_rate is not None else schedule.rate
    if scenario.key == "conservative" and scenario.override_rate is None:
        # Conservative: take max of market rate and a floor, taker-side, no rebate.
        rate = max(schedule.rate, settings.fallback_fee_rate)
    if not schedule.present and scenario.override_rate is None:
        warnings.append("fee schedule missing on market — using configured fallback (estimate)")

    base = (rate or 0.0) * (_min_side(price) ** schedule.exponent)
    # Fees are charged on winnings: pay on win, typically nothing on loss.
    fee_win = base
    fee_lose = 0.0
    if scenario.is_maker:
        if schedule.taker_only:
            fee_win = 0.0  # makers not charged under taker-only schedules
        else:
            fee_win = base * (1.0 - schedule.rebate_rate)
    return FeeBreakdown(
        fee_win=round(fee_win, 8),
        fee_lose=round(fee_lose, 8),
        effective_rate=rate or 0.0,
        schedule_present=schedule.present,
        warnings=warnings,
    )


def breakeven_winrate(entry_price: float, schedule: FeeSchedule, scenario: FeeScenario) -> float:
    """Dynamic fee-inclusive break-even win rate for buying one share at ``entry_price``."""
    fb = compute_fee_per_share(entry_price, schedule, scenario)
    denom = 1.0 - fb.fee_win + fb.fee_lose
    if denom <= 0:
        return 1.0
    be = (entry_price + fb.fee_lose) / denom
    return max(0.0, min(1.0, be))


@dataclass
class TradeEconomics:
    entry_price: float
    effective_entry_price: float
    size: float
    fee_win_per_share: float
    fee_lose_per_share: float
    expected_fee: float | None
    spread_cost: float
    slippage_cost: float
    breakeven_winrate: float
    naive_breakeven: float
    ev_per_share: float | None       # EV given assumed win prob
    ev_total: float | None
    win_prob_assumed: float | None
    schedule_present: bool
    scenario: str
    warnings: list[str] = field(default_factory=list)


def trade_economics(
    *,
    entry_price: float,
    size: float = 1.0,
    schedule: FeeSchedule | None = None,
    scenario: FeeScenario | str = CONSERVATIVE,
    win_prob: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    effective_entry_price: float | None = None,
) -> TradeEconomics:
    """Full per-trade economics. ``win_prob`` is the *assumed* probability for EV; when None,
    EV is reported as None (we never invent an edge). Set it to the market's own implied
    probability or a strategy's signal to test EV explicitly."""
    if isinstance(scenario, str):
        scenario = get_scenario(scenario)
    schedule = schedule or FeeSchedule.from_market(None)

    # Effective entry: a taker crossing the spread pays the ask; spread cost vs mid is explicit.
    mid = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2.0
    eff = effective_entry_price
    spread_cost = 0.0
    if eff is None:
        if scenario.is_maker and best_bid is not None:
            eff = best_bid                       # passive: rest at bid
        elif best_ask is not None:
            eff = best_ask                        # taker: cross to ask
            if mid is not None:
                spread_cost = max(0.0, best_ask - mid)
        else:
            eff = entry_price
    elif mid is not None:
        spread_cost = max(0.0, eff - mid)

    fb = compute_fee_per_share(eff, schedule, scenario)
    be = breakeven_winrate(eff, schedule, scenario)
    naive_be = eff

    ev_share = ev_total = expected_fee = None
    if win_prob is not None:
        w = max(0.0, min(1.0, win_prob))  # clamp once, reuse for EV and expected fee
        ev_share = (w * (1.0 - eff - fb.fee_win)) + ((1.0 - w) * (-eff - fb.fee_lose))
        ev_total = ev_share * size
        expected_fee = (w * fb.fee_win + (1 - w) * fb.fee_lose) * size

    return TradeEconomics(
        entry_price=entry_price,
        effective_entry_price=eff,
        size=size,
        fee_win_per_share=fb.fee_win,
        fee_lose_per_share=fb.fee_lose,
        expected_fee=expected_fee,
        spread_cost=round(spread_cost * size, 8),
        slippage_cost=0.0,
        breakeven_winrate=round(be, 6),
        naive_breakeven=round(naive_be, 6),
        ev_per_share=ev_share,
        ev_total=ev_total,
        win_prob_assumed=win_prob,
        schedule_present=schedule.present,
        scenario=scenario.key,
        warnings=fb.warnings,
    )


def sensitivity(entry_price: float, size: float, schedule: FeeSchedule, win_prob: float | None = None):
    """Run all scenarios so missing maker/taker info never produces a single false number."""
    return {
        s.key: trade_economics(
            entry_price=entry_price, size=size, schedule=schedule, scenario=s, win_prob=win_prob
        )
        for s in (MAKER_LIKE, TAKER_LIKE, CONSERVATIVE)
    }
