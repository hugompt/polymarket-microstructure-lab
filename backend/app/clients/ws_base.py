"""Reconnecting WebSocket base.

Subclasses implement ``subscribe_messages()`` and ``parse(raw)``. The base handles connect,
exponential backoff reconnect, an optional app-level keepalive ping, and emits control events
(``_connect`` / ``_disconnect`` / ``_reconnect``) to the handler so the collector can track
reconnect counts (rule: log WebSocket reconnects).
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from ..config import settings
from ..logging_conf import get_logger

Handler = Callable[[dict], Awaitable[None]]


class BaseWSClient:
    name = "ws"

    def __init__(self, url: str, *, ping_text: str | None = None, ping_interval: float = 10.0):
        self.url = url
        self.ping_text = ping_text
        self.ping_interval = ping_interval
        self.log = get_logger(f"clients.{self.name}")
        self._reconnects = 0

    # -- to override --
    def subscribe_messages(self) -> list[dict | str]:
        return []

    def parse(self, raw: Any) -> list[dict]:
        return []

    async def _keepalive(self, ws) -> None:
        if not self.ping_text:
            return
        try:
            while True:
                await asyncio.sleep(self.ping_interval)
                await ws.send(self.ping_text)
        except Exception:
            return

    # A connection that survives at least this long is treated as healthy and resets the
    # backoff. One that drops sooner keeps escalating, so a server that rejects/closes our
    # subscription cannot trigger a tight reconnect storm.
    MIN_STABLE_SECONDS = 30.0

    async def run(self, handler: Handler, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            started = None
            try:
                async with websockets.connect(
                    self.url, open_timeout=20, ping_interval=20, ping_timeout=20, max_size=8 * 2**20
                ) as ws:
                    started = time.monotonic()
                    await handler({"event_type": "_connect", "source": self.name})
                    for msg in self.subscribe_messages():
                        await ws.send(msg if isinstance(msg, str) else json.dumps(msg))
                    ping_task = asyncio.create_task(self._keepalive(ws))
                    try:
                        async for raw in ws:
                            if stop.is_set():
                                break
                            data = _loads(raw)
                            for event in self.parse(data):
                                await handler(event)
                    finally:
                        ping_task.cancel()
                await handler({"event_type": "_disconnect", "source": self.name})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._reconnects += 1
                self.log.warning("ws_error", url=self.url, error=str(exc), reconnects=self._reconnects)
                await handler(
                    {"event_type": "_reconnect", "source": self.name, "error": str(exc),
                     "reconnects": self._reconnects}
                )
            if stop.is_set():
                break
            # Stability-aware backoff: reset only after a healthy session; otherwise escalate.
            lasted = (time.monotonic() - started) if started is not None else 0.0
            if lasted >= self.MIN_STABLE_SECONDS:
                attempt = 0
            else:
                attempt += 1
            backoff = min(settings.backoff_base_seconds * (2**attempt), settings.backoff_cap_seconds)
            backoff += random.uniform(0, settings.backoff_base_seconds)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass


def _loads(raw) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.upper() in {"PING", "PONG"}:
            return {"_control": s}
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return {"_unparsed": s}
    return raw
