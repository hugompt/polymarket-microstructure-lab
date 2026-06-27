from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from ...db import models
from ...db.session import get_db
from ...util.timeutil import now_utc, to_utc

router = APIRouter(tags=["data-quality"])

_GAP_RE = re.compile(r"gap\s+([\d.]+)s")


@router.get("/data-quality")
def data_quality(
    detail: bool = Query(False, description="return per-token feeds instead of per-source"),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    now = now_utc()

    # --- totals via a single SQL aggregate (not a per-row Python loop) ---
    agg = db.execute(select(
        func.coalesce(func.sum(models.FeedHealth.messages), 0),
        func.coalesce(func.sum(models.FeedHealth.duplicates), 0),
        func.coalesce(func.sum(models.FeedHealth.stale), 0),
        func.coalesce(func.sum(models.FeedHealth.out_of_order), 0),
        func.coalesce(func.sum(models.FeedHealth.reconnects), 0),
        func.coalesce(func.sum(models.FeedHealth.rejected), 0),
        func.coalesce(func.sum(models.FeedHealth.gaps), 0),
    )).one()
    totals = {
        "messages": int(agg[0]), "duplicates": int(agg[1]), "stale": int(agg[2]),
        "out_of_order": int(agg[3]), "reconnects": int(agg[4]), "rejected": int(agg[5]),
        "gaps": int(agg[6]),
    }
    totals["raw"] = db.scalar(select(func.count()).select_from(models.MarketSnapshotRaw)) or 0
    totals["clean"] = db.scalar(select(func.count()).select_from(models.OrderbookSnapshot)
                                .where(models.OrderbookSnapshot.accepted.is_(True))) or 0

    # --- feeds: aggregated by source by default; per-token only when ?detail=true ---
    feeds = []
    if detail:
        for f in db.scalars(select(models.FeedHealth)
                            .order_by(models.FeedHealth.messages.desc()).limit(limit)):
            age = (now - to_utc(f.last_message_at)).total_seconds() if f.last_message_at else None
            feeds.append({
                "source": f.source, "token_id": f.token_id, "asset_symbol": f.asset_symbol,
                "connected": f.connected,
                "last_message_age_s": round(age, 1) if age is not None else None,
                "messages": f.messages, "duplicates": f.duplicates, "stale": f.stale,
                "out_of_order": f.out_of_order, "reconnects": f.reconnects, "rejected": f.rejected,
                "gaps": f.gaps,
            })
    else:
        rows = db.execute(select(
            models.FeedHealth.source, func.count().label("n"),
            func.sum(cast(models.FeedHealth.connected, Integer)),
            func.max(models.FeedHealth.last_message_at),
            func.sum(models.FeedHealth.messages), func.sum(models.FeedHealth.duplicates),
            func.sum(models.FeedHealth.stale), func.sum(models.FeedHealth.out_of_order),
            func.sum(models.FeedHealth.reconnects), func.sum(models.FeedHealth.rejected),
            func.sum(models.FeedHealth.gaps),
        ).group_by(models.FeedHealth.source)).all()
        for src, n, conn, last_msg, msgs, dup, stale, ooo, reconn, rej, gaps in rows:
            age = (now - to_utc(last_msg)).total_seconds() if last_msg else None
            feeds.append({
                "source": src, "token_id": None, "asset_symbol": None, "feeds": int(n),
                "connected": bool(conn), "connected_feeds": int(conn or 0),
                "last_message_age_s": round(age, 1) if age is not None else None,
                "messages": int(msgs or 0), "duplicates": int(dup or 0), "stale": int(stale or 0),
                "out_of_order": int(ooo or 0), "reconnects": int(reconn or 0),
                "rejected": int(rej or 0), "gaps": int(gaps or 0),
            })

    # --- per-market gap analysis (contract shape: expected/received/gap_count/max_gap_s) ---
    top_markets = db.execute(
        select(models.DataQualityEvent.market_id, func.count().label("c"))
        .where(models.DataQualityEvent.event_type == "gap",
               models.DataQualityEvent.market_id.is_not(None))
        .group_by(models.DataQualityEvent.market_id)
        .order_by(func.count().desc()).limit(100)
    ).all()
    market_gaps = []
    for market_id, gap_count in top_markets:
        m = db.get(models.Market, market_id)
        received = None
        if m:
            toks = [t for t in (m.up_token_id, m.down_token_id) if t]
            if toks:
                received = db.scalar(select(func.count()).select_from(models.OrderbookSnapshot)
                                     .where(models.OrderbookSnapshot.token_id.in_(toks))) or 0
        # max gap seconds parsed from the (internal, controlled) event messages
        msgs = db.scalars(select(models.DataQualityEvent.message)
                          .where(models.DataQualityEvent.event_type == "gap",
                                 models.DataQualityEvent.market_id == market_id).limit(500)).all()
        secs = [float(x) for msg in msgs if msg for x in _GAP_RE.findall(msg)]
        market_gaps.append({
            "market_id": market_id, "slug": m.slug if m else None,
            "gap_count": int(gap_count),
            "received": received,
            "expected": (received + int(gap_count)) if received is not None else None,
            "max_gap_s": round(max(secs), 1) if secs else None,
        })

    api_errors = []
    for e in db.scalars(select(models.ApiCallLog).where(models.ApiCallLog.ok.is_(False))
                        .order_by(models.ApiCallLog.ts.desc()).limit(100)):
        api_errors.append({"ts": e.ts.isoformat() if e.ts else None, "client": e.client,
                           "path": e.path, "status_code": e.status_code, "error": e.error})

    return {"totals": totals, "feeds": feeds, "market_gaps": market_gaps, "api_errors": api_errors}
