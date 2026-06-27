"""Pure performance statistics. No pandas/numpy — stdlib only, fully testable.

Every metric degrades gracefully on empty / tiny samples and the caller is expected to
surface ``is_low_sample`` so results are never overstated (rule: make low-sample obvious).
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

LOW_SAMPLE_THRESHOLD = 30


def win_rate(wins: Sequence[bool]) -> float | None:
    if not wins:
        return None
    return sum(1 for w in wins if w) / len(wins)


def profit_factor(pnls: Sequence[float]) -> float | None:
    gains = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else None
    return gains / losses


def avg_win(pnls: Sequence[float]) -> float | None:
    wins = [p for p in pnls if p > 0]
    return sum(wins) / len(wins) if wins else None


def avg_loss(pnls: Sequence[float]) -> float | None:
    losses = [p for p in pnls if p < 0]
    return sum(losses) / len(losses) if losses else None


def cumulative(pnls: Iterable[float]) -> list[float]:
    out, run = [], 0.0
    for p in pnls:
        run += p
        out.append(round(run, 8))
    return out


def max_drawdown(pnls: Sequence[float]) -> float:
    """Most-negative peak-to-trough on the cumulative-PnL equity curve. Returns <= 0."""
    peak = 0.0
    run = 0.0
    mdd = 0.0
    for p in pnls:
        run += p
        peak = max(peak, run)
        mdd = min(mdd, run - peak)
    return round(mdd, 8)


def sharpe_like(pnls: Sequence[float]) -> float | None:
    """Mean / stdev of per-trade PnL (not annualised) — a simple risk-adjusted ratio."""
    n = len(pnls)
    if n < 2:
        return None
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return round(mean / sd, 4)


def is_low_sample(n: int, threshold: int = LOW_SAMPLE_THRESHOLD) -> bool:
    return n < threshold


def summarize(pnls: Sequence[float], wins: Sequence[bool] | None = None) -> dict[str, Any]:
    n = len(pnls)
    wr = win_rate(wins) if wins is not None else win_rate([p > 0 for p in pnls])
    return {
        "n": n,
        "gross_pnl": round(sum(pnls), 6) if pnls else 0.0,
        "win_rate": wr,
        "profit_factor": _finite(profit_factor(pnls)),
        "avg_win": avg_win(pnls),
        "avg_loss": avg_loss(pnls),
        "max_drawdown": max_drawdown(pnls),
        "sharpe_like": sharpe_like(pnls),
        "is_low_sample": is_low_sample(n),
    }


def _finite(x: float | None) -> float | None:
    if x is None:
        return None
    if math.isinf(x):
        return None  # JSON-safe; "inf profit factor" => no losses
    return round(x, 6)


def group_breakdown(
    rows: Iterable[dict],
    key_fn: Callable[[dict], Any],
    *,
    pnl_key: str = "pnl",
    won_key: str = "won",
    volume_fn: Callable[[dict], float] | None = None,
) -> list[dict]:
    """Aggregate rows by a key into [{key, n, pnl, win_rate, volume, is_low_sample}], sorted by key."""
    buckets: dict[Any, list[dict]] = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is None:
            continue
        buckets[k].append(r)
    out = []
    for k, items in buckets.items():
        pnls = [float(i.get(pnl_key) or 0.0) for i in items]
        wins = [bool(i.get(won_key)) for i in items if i.get(won_key) is not None]
        vol = sum(volume_fn(i) for i in items) if volume_fn else None
        out.append({
            "key": k,
            "n": len(items),
            "pnl": round(sum(pnls), 6),
            "win_rate": win_rate(wins) if wins else None,
            "volume": round(vol, 4) if vol is not None else None,
            "is_low_sample": is_low_sample(len(items)),
        })
    return sorted(out, key=lambda d: (str(type(d["key"])), d["key"]))


def histogram(values: Iterable[float], buckets: Sequence[tuple[float, float, str]]) -> list[dict]:
    counts = {label: 0 for _, _, label in buckets}
    for v in values:
        if v is None:
            continue
        for lo, hi, label in buckets:
            if lo <= v < hi:
                counts[label] += 1
                break
    return [{"bucket": label, "n": counts[label]} for _, _, label in buckets]
