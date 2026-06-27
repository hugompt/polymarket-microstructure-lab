"""Nearest-before / nearest-after lookup over time-ordered items.

Pure & unit-testable. Used to attach the orderbook/price context around each wallet trade
(rule: nearest orderbook snapshot before/after, nearest Binance/Chainlink tick before/after).
"""
from __future__ import annotations

import bisect
from collections.abc import Callable, Sequence
from typing import Any


def nearest_before_after(
    items: Sequence[Any],
    target: float,
    *,
    key: Callable[[Any], float],
    already_sorted: bool = False,
) -> tuple[Any | None, Any | None]:
    """Return (nearest_before_or_at, nearest_after) around ``target``.

    ``before`` is the item with the greatest key <= target; ``after`` is the item with the
    smallest key > target. Either may be None.
    """
    if not items:
        return None, None
    seq = list(items) if already_sorted else sorted(items, key=key)
    keys = [key(i) for i in seq]
    idx = bisect.bisect_right(keys, target)  # first index with key > target
    after = seq[idx] if idx < len(seq) else None
    before = seq[idx - 1] if idx - 1 >= 0 else None
    return before, after


def nearest(items: Sequence[Any], target: float, *, key: Callable[[Any], float]) -> Any | None:
    """Single nearest item (either side) by absolute key distance."""
    before, after = nearest_before_after(items, target, key=key)
    candidates = [c for c in (before, after) if c is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(key(c) - target))
