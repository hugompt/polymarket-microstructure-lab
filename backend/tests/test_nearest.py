"""Nearest-before / nearest-after lookup (trade enrichment core)."""
from __future__ import annotations

from app.util.nearest import nearest, nearest_before_after


def test_nearest_before_after_basic():
    items = [(10, "a"), (20, "b"), (30, "c")]
    before, after = nearest_before_after(items, 25, key=lambda x: x[0])
    assert before == (20, "b")
    assert after == (30, "c")


def test_exact_match_is_before():
    items = [(10, "a"), (20, "b")]
    before, after = nearest_before_after(items, 20, key=lambda x: x[0])
    assert before == (20, "b")     # <= target counts as before
    assert after is None


def test_before_none_when_target_precedes_all():
    items = [(10, "a"), (20, "b")]
    before, after = nearest_before_after(items, 5, key=lambda x: x[0])
    assert before is None
    assert after == (10, "a")


def test_after_none_when_target_after_all():
    items = [(10, "a"), (20, "b")]
    before, after = nearest_before_after(items, 99, key=lambda x: x[0])
    assert before == (20, "b")
    assert after is None


def test_empty():
    assert nearest_before_after([], 5, key=lambda x: x) == (None, None)
    assert nearest([], 5, key=lambda x: x) is None


def test_nearest_picks_closest_side():
    items = [(10, "a"), (40, "b")]
    assert nearest(items, 12, key=lambda x: x[0]) == (10, "a")
    assert nearest(items, 35, key=lambda x: x[0]) == (40, "b")


def test_unsorted_input_is_sorted():
    items = [(30, "c"), (10, "a"), (20, "b")]
    before, after = nearest_before_after(items, 25, key=lambda x: x[0])
    assert before == (20, "b")
    assert after == (30, "c")
