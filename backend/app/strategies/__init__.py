"""Paper-trading strategy lab. SIMULATION ONLY — never places real orders."""
from __future__ import annotations

from .registry import REGISTRY, get_strategy, list_strategies

__all__ = ["REGISTRY", "get_strategy", "list_strategies"]
