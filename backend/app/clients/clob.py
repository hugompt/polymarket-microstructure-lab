"""CLOB API client — PUBLIC read-only market data only.

Base: https://clob.polymarket.com
Used: /book, /books, /midpoint, /spread, /price, /prices-history, /last-trade-price

HARD RULE: this client exposes NO trading methods. Order placement / cancellation /
signing endpoints are intentionally absent.
"""
from __future__ import annotations

from ..config import settings
from .base import BaseHTTPClient


class ClobClient(BaseHTTPClient):
    def __init__(self, **kw) -> None:
        super().__init__(settings.clob_base_url, "clob", **kw)

    async def book(self, token_id: str) -> dict:
        # 404 = no open book for this token right now (market not yet open or already closed).
        # Treat it as an empty book, not an API error, so it does not flood the error log.
        data = await self.request_json("GET", "/book", params={"token_id": token_id},
                                       expected_statuses={404})
        return data if isinstance(data, dict) else {}

    async def books(self, token_ids: list[str]) -> list[dict]:
        """Batch orderbooks (POST /books)."""
        body = [{"token_id": t} for t in token_ids]
        data = await self.request_json("POST", "/books", json_body=body)
        return data if isinstance(data, list) else []

    async def midpoint(self, token_id: str) -> float | None:
        data = await self.get("/midpoint", token_id=token_id)
        return _num(data, "mid")

    async def spread(self, token_id: str) -> float | None:
        data = await self.get("/spread", token_id=token_id)
        return _num(data, "spread")

    async def price(self, token_id: str, side: str = "buy") -> float | None:
        data = await self.get("/price", token_id=token_id, side=side)
        return _num(data, "price")

    async def last_trade_price(self, token_id: str) -> float | None:
        try:
            data = await self.get("/last-trade-price", token_id=token_id)
        except Exception:
            return None
        return _num(data, "price")

    async def prices_history(
        self,
        token_id: str,
        *,
        interval: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        fidelity: int | None = None,
    ) -> list[dict]:
        """Time series of mid prices. Returns the ``history`` list [{t, p}]."""
        params: dict = {"market": token_id}
        if interval:
            params["interval"] = interval
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts
        if fidelity is not None:
            params["fidelity"] = fidelity
        data = await self.request_json("GET", "/prices-history", params=params)
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            return data["history"]
        if isinstance(data, list):
            return data
        return []


def _num(data, key: str) -> float | None:
    if isinstance(data, dict) and key in data:
        try:
            return float(data[key])
        except (TypeError, ValueError):
            return None
    return None
