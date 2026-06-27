"""Data API client (public user positions / trades / activity / value).

Base: https://data-api.polymarket.com  (read-only)
All endpoints take ``user=<address>``. Pagination via limit/offset where supported.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from .base import BaseHTTPClient
from .gamma import _as_list


class DataApiClient(BaseHTTPClient):
    def __init__(self, **kw) -> None:
        super().__init__(settings.data_base_url, "data", **kw)

    async def trades(self, user: str, *, limit: int = 100, offset: int = 0, **params) -> list[dict]:
        data = await self.get("/trades", user=user, limit=limit, offset=offset, **params)
        return _as_list(data)

    async def activity(self, user: str, *, limit: int = 100, offset: int = 0, **params) -> list[dict]:
        data = await self.get("/activity", user=user, limit=limit, offset=offset, **params)
        return _as_list(data)

    async def positions(self, user: str, *, limit: int = 100, offset: int = 0, **params) -> list[dict]:
        data = await self.get("/positions", user=user, limit=limit, offset=offset, **params)
        return _as_list(data)

    async def value(self, user: str) -> float:
        """Portfolio value (USDC). Endpoint returns [{user, value}]."""
        data = await self.get("/value", user=user)
        rows = _as_list(data)
        if rows and isinstance(rows[0], dict) and "value" in rows[0]:
            try:
                return float(rows[0]["value"])
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    async def iter_trades(self, user: str, *, page_size: int = 500, max_pages: int = 200, **params):
        """Walk the full trade history with offset paging."""
        offset = 0
        for _ in range(max_pages):
            batch = await self.trades(user, limit=page_size, offset=offset, **params)
            if not batch:
                return
            for t in batch:
                yield t
            if len(batch) < page_size:
                return
            offset += page_size

    async def iter_activity(self, user: str, *, page_size: int = 500, max_pages: int = 200, **params):
        offset = 0
        for _ in range(max_pages):
            batch = await self.activity(user, limit=page_size, offset=offset, **params)
            if not batch:
                return
            for a in batch:
                yield a
            if len(batch) < page_size:
                return
            offset += page_size


def first_value(data: Any) -> float:  # pragma: no cover - small helper
    rows = _as_list(data)
    if rows and "value" in rows[0]:
        return float(rows[0]["value"])
    return 0.0
