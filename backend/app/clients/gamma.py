"""Gamma API client (market / event / profile discovery).

Base: https://gamma-api.polymarket.com  (read-only)
Endpoints used: /markets, /events, /markets/{id}, /events/{id}
Returns raw lists/dicts; parsing & classification happen in services.discovery.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from .base import BaseHTTPClient


class GammaClient(BaseHTTPClient):
    def __init__(self, **kw) -> None:
        super().__init__(settings.gamma_base_url, "gamma", **kw)

    async def markets(self, **params) -> list[dict]:
        data = await self.get("/markets", **params)
        return _as_list(data)

    async def events(self, **params) -> list[dict]:
        data = await self.get("/events", **params)
        return _as_list(data)

    async def market_by_id(self, gamma_id: str | int) -> dict | None:
        try:
            data = await self.get(f"/markets/{gamma_id}")
        except Exception:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    async def events_by_slug(self, slug: str) -> list[dict]:
        return await self.events(slug=slug)

    async def iter_events(self, *, page_size: int = 100, max_pages: int = 20, **params):
        """Paginate /events via offset until a short page or max_pages is hit."""
        offset = 0
        for _ in range(max_pages):
            batch = await self.events(limit=page_size, offset=offset, **params)
            if not batch:
                return
            for ev in batch:
                yield ev
            if len(batch) < page_size:
                return
            offset += page_size


def _as_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        # Some endpoints wrap results in {"data": [...]}.
        for key in ("data", "events", "markets", "results"):
            if isinstance(data.get(key), list):
                return [d for d in data[key] if isinstance(d, dict)]
        return [data]
    return []
