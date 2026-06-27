"""Typed, tolerant, read-only HTTP/WS clients for public Polymarket data.

There is deliberately NO trading client. CLOB order-placement endpoints are never called.
"""
from __future__ import annotations

from .base import BaseHTTPClient, BudgetExceededError, RequestBudget, TokenBucket
from .clob import ClobClient
from .data_api import DataApiClient
from .gamma import GammaClient

__all__ = [
    "BaseHTTPClient",
    "BudgetExceededError",
    "RequestBudget",
    "TokenBucket",
    "GammaClient",
    "DataApiClient",
    "ClobClient",
]
