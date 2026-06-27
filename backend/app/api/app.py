"""FastAPI application factory.

Read-only JSON API for the dashboard. Sync handlers (FastAPI runs them in a threadpool) with
a sync SQLAlchemy session. An OPTIONAL background scheduler (off by default) can periodically
run discovery + wallet sync; the live collector is a separate process (`python -m app collect`).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..logging_conf import configure_logging, get_logger
from .routers import data_quality, export, health, markets, paper, strategies, wallets

log = get_logger("api")


async def _background_jobs(app: FastAPI) -> None:
    import random

    from ..clients.base import BudgetExceededError
    from ..services.discovery import run_discovery
    from ..services.wallet_sync import sync_wallet

    while True:
        try:
            await run_discovery(include_closed=False, max_pages_open=4)
            if settings.target_wallet:
                await sync_wallet(settings.target_wallet, max_pages=4)
        except BudgetExceededError as exc:
            # The process-global request budget never replenishes — stop, don't tight-loop.
            log.error("bg_budget_exhausted_stopping", error=str(exc))
            return
        except Exception as exc:
            log.warning("bg_jobs_error", error=str(exc))
        # Jittered sleep so retries/failures don't synchronise into a tight loop.
        await asyncio.sleep(max(30.0, settings.discovery_poll_seconds) + random.uniform(0, 5))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level, settings.log_json)
    task = None
    if os.getenv("PML_API_BACKGROUND_JOBS", "false").lower() in ("1", "true", "yes"):
        log.info("api_background_jobs_enabled")
        task = asyncio.create_task(_background_jobs(app))
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    # Stop any API-launched paper-trading sessions so nothing lingers after shutdown.
    for _sid, (engine, t) in list(paper._RUNNING.items()):
        engine.stop.set()
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t


def create_app() -> FastAPI:
    app = FastAPI(
        title="polymarket-microstructure-lab",
        version="0.1.0",
        description="Read-only research API for Polymarket crypto Up/Down markets. NO TRADING.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        # Scoped to the dashboard origin(s); only GET/POST are used (POST = /strategies/run).
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    for r in (health.router, markets.router, wallets.router, data_quality.router,
              strategies.router, export.router, paper.router):
        app.include_router(r, prefix="/api")

    @app.get("/")
    def root():
        return {"app": settings.app_name, "status": "ok",
                "docs": "/docs", "note": "read-only research; no trading"}

    return app


app = create_app()
