"""Base async HTTP client: rate limiting, retries/backoff, request budget, call logging.

Tolerant by design: returns parsed JSON (list or dict) and never assumes a fixed schema.
Every outbound call is throttled (token bucket), retried with exponential backoff + jitter
on transient failures, counted against a hard request budget, and summarised to
``api_call_logs`` (best-effort) plus structured logs.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from ..config import Settings, settings as default_settings
from ..logging_conf import get_logger
from ..util.timeutil import now_utc

log = get_logger("clients.http")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class BudgetExceededError(RuntimeError):
    """Raised when the process-wide request budget is exhausted (safety stop)."""


class RequestBudget:
    """Hard ceiling on total outbound requests for a process run."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.used = 0
        self._lock = asyncio.Lock()

    async def consume(self) -> int:
        async with self._lock:
            if self.used >= self.total:
                raise BudgetExceededError(
                    f"request budget exhausted ({self.used}/{self.total})"
                )
            self.used += 1
            return self.total - self.used

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)


class TokenBucket:
    """Async token bucket: ``rate`` tokens/sec, capacity ``burst``."""

    def __init__(self, rate: float, burst: int) -> None:
        self.rate = max(rate, 0.01)
        self.capacity = max(burst, 1)
        self._tokens = float(self.capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                await asyncio.sleep(deficit / self.rate)


# Process-wide shared budget so every client counts against one ceiling.
_SHARED_BUDGET: RequestBudget | None = None


def shared_budget(total: int | None = None) -> RequestBudget:
    global _SHARED_BUDGET
    if _SHARED_BUDGET is None:
        _SHARED_BUDGET = RequestBudget(total or default_settings.request_budget)
    return _SHARED_BUDGET


def _persist_call_log(record: dict) -> None:
    """Best-effort write to api_call_logs. Never raises into the request path."""
    try:
        from ..db import models
        from ..db.session import session_scope

        with session_scope() as db:
            db.add(models.ApiCallLog(**record))
    except Exception as exc:  # pragma: no cover - logging must never break requests
        log.debug("api_call_log_persist_failed", error=str(exc))


class BaseHTTPClient:
    def __init__(
        self,
        base_url: str,
        name: str,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        budget: RequestBudget | None = None,
        persist_logs: bool = True,
    ) -> None:
        self.name = name
        self.settings = settings or default_settings
        self.persist_logs = persist_logs
        self.budget = budget or shared_budget(self.settings.request_budget)
        self.bucket = TokenBucket(self.settings.rate_limit_per_sec, self.settings.rate_limit_burst)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"User-Agent": self.settings.http_user_agent, "Accept": "application/json"},
            timeout=self.settings.http_timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BaseHTTPClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def _backoff(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.settings.backoff_cap_seconds)
        base = self.settings.backoff_base_seconds * (2 ** attempt)
        jitter = random.uniform(0, self.settings.backoff_base_seconds)
        return min(base + jitter, self.settings.backoff_cap_seconds)

    async def request_json(
        self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None,
        expected_statuses: set[int] | None = None,
    ) -> Any:
        """``expected_statuses`` are non-2xx codes the caller treats as a normal outcome (e.g. a
        404 from /book just means "this market has no open book right now"). They are logged as
        ok=True and return None instead of raising or polluting the API error log."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        last_exc: Exception | None = None

        for attempt in range(self.settings.max_retries + 1):
            remaining = await self.budget.consume()
            await self.bucket.acquire()
            t0 = time.monotonic()
            status: int | None = None
            ok = False
            err: str | None = None
            nbytes: int | None = None
            try:
                resp = await self._client.request(method, path, params=params, json=json_body)
                status = resp.status_code
                nbytes = len(resp.content)
                if expected_statuses and status in expected_statuses:
                    self._log_call(method, path, params, status, t0, attempt + 1,
                                   ok=True, err=None, nbytes=nbytes, remaining=remaining)
                    try:
                        return resp.json()
                    except Exception:
                        return None
                if status in RETRYABLE_STATUS:
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    err = f"retryable status {status}"
                    self._log_call(method, path, params, status, t0, attempt + 1,
                                   ok=False, err=err, nbytes=nbytes, remaining=remaining)
                    if attempt < self.settings.max_retries:
                        await asyncio.sleep(self._backoff(attempt, retry_after))
                        continue
                    resp.raise_for_status()
                resp.raise_for_status()
                ok = True
                data = resp.json()
                self._log_call(method, path, params, status, t0, attempt + 1,
                               ok=True, err=None, nbytes=nbytes, remaining=remaining)
                return data
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                err = f"{type(exc).__name__}: {exc}"
                self._log_call(method, path, params, status, t0, attempt + 1,
                               ok=False, err=err, nbytes=nbytes, remaining=remaining)
                if attempt < self.settings.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                err = f"HTTPStatusError {exc.response.status_code}"
                self._log_call(method, path, params, exc.response.status_code, t0, attempt + 1,
                               ok=False, err=err, nbytes=nbytes, remaining=remaining)
                # Non-retryable 4xx (other than 429) -> stop.
                if exc.response.status_code not in RETRYABLE_STATUS:
                    raise
                if attempt < self.settings.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue

        assert last_exc is not None
        raise last_exc

    def _log_call(self, method, path, params, status, t0, attempt, *, ok, err, nbytes, remaining):
        duration_ms = (time.monotonic() - t0) * 1000.0
        host = str(self._client.base_url.host)
        query = "&".join(f"{k}={v}" for k, v in params.items())[:480]
        log.info(
            "api_call",
            client=self.name,
            method=method,
            host=host,
            path=path,
            status=status,
            ms=round(duration_ms, 1),
            attempt=attempt,
            ok=ok,
            error=err,
        )
        if self.persist_logs:
            _persist_call_log(
                {
                    "ts": now_utc(),
                    "client": self.name,
                    "method": method,
                    "host": host,
                    "path": path,
                    "query": query,
                    "status_code": status,
                    "duration_ms": duration_ms,
                    "ok": ok,
                    "attempt": attempt,
                    "response_bytes": nbytes,
                    "error": err,
                    "budget_remaining": remaining,
                }
            )

    async def get(self, path: str, **params) -> Any:
        return await self.request_json("GET", path, params=params)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
