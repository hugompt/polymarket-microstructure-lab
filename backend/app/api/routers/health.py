from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from ...clients.base import shared_budget
from ...config import settings
from ...db import models
from ...db.session import get_db
from ...util.timeutil import now_utc, to_utc

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    now = now_utc()
    day_ago = now - timedelta(days=1)
    db_ok = True
    try:
        db.execute(select(func.count()).select_from(models.Market))
    except Exception:
        db_ok = False

    def count(model, *where):
        stmt = select(func.count()).select_from(model)
        for w in where:
            stmt = stmt.where(w)
        return db.scalar(stmt) or 0

    counts = {
        "markets": count(models.Market),
        "live_markets": count(models.Market, models.Market.status == "live"),
        "upcoming_markets": count(models.Market, models.Market.status == "upcoming"),
        "trades": count(models.Trade),
        "orderbook_snapshots_today": count(models.OrderbookSnapshot,
                                           models.OrderbookSnapshot.received_ts >= day_ago),
        "ticks_today": count(models.CryptoPriceTick, models.CryptoPriceTick.received_ts >= day_ago),
        "api_errors_today": count(models.ApiCallLog, models.ApiCallLog.ok.is_(False),
                                  models.ApiCallLog.ts >= day_ago),
    }

    # Aggregate feed health BY SOURCE so the response stays small (a few rows) instead of
    # returning one row per token (hundreds of rows / >100KB).
    feeds = []
    rows = db.execute(
        select(
            models.FeedHealth.source,
            func.count().label("n"),
            func.sum(cast(models.FeedHealth.connected, Integer)).label("connected"),
            func.max(models.FeedHealth.last_message_at).label("last_msg"),
            func.sum(models.FeedHealth.messages),
            func.sum(models.FeedHealth.duplicates),
            func.sum(models.FeedHealth.stale),
            func.sum(models.FeedHealth.out_of_order),
            func.sum(models.FeedHealth.reconnects),
            func.sum(models.FeedHealth.rejected),
        ).group_by(models.FeedHealth.source)
    ).all()
    for src, n, conn, last_msg, msgs, dup, stale, ooo, reconn, rej in rows:
        age = (now - to_utc(last_msg)).total_seconds() if last_msg else None
        feeds.append({
            "source": src, "token_id": None, "asset_symbol": None, "feeds": int(n),
            "connected": bool(conn), "connected_feeds": int(conn or 0),
            "last_message_age_s": round(age, 1) if age is not None else None,
            "messages": int(msgs or 0), "duplicates": int(dup or 0), "stale": int(stale or 0),
            "out_of_order": int(ooo or 0), "reconnects": int(reconn or 0), "rejected": int(rej or 0),
        })

    last_disc = db.get(models.AppSetting, "last_discovery_at")
    last_sync = db.get(models.AppSetting, "last_wallet_sync_at")
    last_discovery_at = (last_disc.value or {}).get("at") if last_disc else None
    last_wallet_sync_at = (last_sync.value or {}).get("at") if last_sync else None

    warnings = []
    if not db_ok:
        warnings.append("Database not reachable.")
    if not feeds or not any(f["connected"] for f in feeds):
        warnings.append("No live data feeds connected. Run `make collect`.")
    # One summary warning for stale feeds rather than one per token.
    stale_cut = now - timedelta(seconds=settings.stale_after_seconds)
    n_stale = db.scalar(select(func.count()).select_from(models.FeedHealth).where(
        models.FeedHealth.last_message_at.is_not(None),
        models.FeedHealth.last_message_at < stale_cut)) or 0
    if n_stale:
        stale_sources = sorted({f["source"] for f in feeds if (f["last_message_age_s"] or 0)
                                > settings.stale_after_seconds})
        warnings.append(f"{n_stale} feed(s) stale (no message in >{settings.stale_after_seconds:.0f}s)"
                        + (f" across {', '.join(stale_sources)}" if stale_sources else "") + ".")
    if last_discovery_at is None:
        warnings.append("No market discovery has run yet. Run `make setup`.")
    if last_wallet_sync_at is None:
        warnings.append("Target wallet not synced yet. Run `make sync-wallet`.")

    return {
        "status": "ok" if db_ok else "degraded",
        "time_utc": now.isoformat(),
        "db_ok": db_ok,
        "request_budget_remaining": shared_budget().remaining,
        "counts": counts,
        "feeds": feeds,
        "last_discovery_at": last_discovery_at,
        "last_wallet_sync_at": last_wallet_sync_at,
        "warnings": warnings,
    }
