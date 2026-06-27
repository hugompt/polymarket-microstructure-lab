"""Strategy registry."""
from __future__ import annotations

import random

from .base import Strategy
from .baselines import ALL_STRATEGIES

REGISTRY: dict[str, type[Strategy]] = {s.key: s for s in ALL_STRATEGIES}


def get_strategy(key: str, params: dict | None = None, *, seed: int | None = None) -> Strategy:
    cls = REGISTRY.get(key)
    if cls is None:
        raise KeyError(f"unknown strategy '{key}'. known: {sorted(REGISTRY)}")
    rng = random.Random(seed if seed is not None else (params or {}).get("seed", 1234))
    return cls(params=params, rng=rng)


def list_strategies() -> list[dict]:
    return [
        {
            "key": s.key,
            "name": s.name,
            "description": s.description,
            "requires": s.requires,
            "params_schema": s.params_schema,
        }
        for s in ALL_STRATEGIES
    ]
