"""Target-wallet watcher.

Fetches public trades / activity / positions / value for a configured target bot wallet
(set ``PML_TARGET_WALLET`` to a PUBLIC on-chain address, never a private key) and upserts them
idempotently (dedup hash). Trades are linked to discovered markets by ``condition_id``.

This stores *raw reported* data only. Independent PnL reconstruction and the skeptical
accounting live in ``analysis.wallet`` — kept separate so reported numbers are never silently
treated as ground truth.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clients.data_api import DataApiClient
from ..config import settings
from ..db import models
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..util.normalize import dedup_hash, to_float
from ..util.timeutil import epoch_to_utc, now_utc, parse_any_time

log = get_logger("services.wallet_sync")


def normalize_address(addr: str) -> str:
    return (addr or "").strip().lower()


async def fetch_wallet(
    address: str, *, max_pages: int = 50, page_size: int = 500
) -> dict:
    address = normalize_address(address)
    client = DataApiClient()
    try:
        trades = [t async for t in client.iter_trades(address, page_size=page_size, max_pages=max_pages)]
        activity = [a async for a in client.iter_activity(address, page_size=page_size, max_pages=max_pages)]
        positions = await client.positions(address, limit=500)
        value = await client.value(address)
    finally:
        await client.aclose()
    log.info("wallet_fetch", address=address, trades=len(trades), activity=len(activity),
             positions=len(positions), value=value)
    return {"trades": trades, "activity": activity, "positions": positions, "value": value}


def _ensure_wallet(db: Session, address: str) -> models.Wallet:
    address = normalize_address(address)
    w = db.scalar(select(models.Wallet).where(models.Wallet.address == address))
    if w is None:
        w = models.Wallet(
            address=address,
            is_target=(address == normalize_address(settings.target_wallet)),
            label=settings.target_profile if address == normalize_address(settings.target_wallet) else None,
        )
        db.add(w)
        db.flush()
    return w


def _market_id_for(db: Session, condition_id: str | None, cache: dict) -> int | None:
    if not condition_id:
        return None
    if condition_id in cache:
        return cache[condition_id]
    m = db.scalar(select(models.Market.id).where(models.Market.condition_id == condition_id))
    cache[condition_id] = m
    return m


def persist_profile(db: Session, address: str, sample: dict) -> None:
    address = normalize_address(address)
    w = _ensure_wallet(db, address)
    name = sample.get("name") or sample.get("pseudonym")
    prof = db.scalar(
        select(models.WalletProfile).where(models.WalletProfile.address == address)
    )
    if prof is None:
        prof = models.WalletProfile(wallet_id=w.id, address=address)
        db.add(prof)
    prof.name = sample.get("name") or prof.name
    prof.pseudonym = sample.get("pseudonym") or prof.pseudonym
    prof.bio = sample.get("bio") or prof.bio
    prof.profile_image = sample.get("profileImage") or sample.get("profileImageOptimized") or prof.profile_image
    prof.fetched_at = now_utc()
    prof.raw = {k: sample.get(k) for k in ("name", "pseudonym", "bio", "profileImage", "proxyWallet")}
    if name and not w.label:
        w.label = name


def persist_trades(db: Session, address: str, rows: list[dict]) -> dict:
    address = normalize_address(address)
    _ensure_wallet(db, address)
    cache: dict = {}
    seen: set[str] = set()
    new = skipped = 0
    for r in rows:
        h = dedup_hash(
            r.get("transactionHash"), r.get("asset"), r.get("side"),
            r.get("price"), r.get("size"), r.get("timestamp"), r.get("outcome"),
        )
        exists = h in seen or db.scalar(
            select(models.Trade.id).where(
                models.Trade.wallet_address == address, models.Trade.dedup_hash == h
            )
        )
        if exists:
            skipped += 1
            continue
        seen.add(h)
        price = to_float(r.get("price"))
        size = to_float(r.get("size"))
        ts = r.get("timestamp")
        t = models.Trade(
            wallet_address=address,
            proxy_wallet=r.get("proxyWallet"),
            condition_id=r.get("conditionId"),
            asset=str(r.get("asset")) if r.get("asset") is not None else None,
            market_id=_market_id_for(db, r.get("conditionId"), cache),
            event_slug=r.get("eventSlug"),
            slug=r.get("slug"),
            side=(r.get("side") or "").upper() or None,
            outcome=r.get("outcome"),
            outcome_index=r.get("outcomeIndex"),
            price=price,
            size=size,
            notional=(price * size) if (price is not None and size is not None) else None,
            timestamp_epoch=int(ts) if ts is not None else None,
            ts_utc=epoch_to_utc(ts),
            transaction_hash=r.get("transactionHash"),
            title=r.get("title"),
            name=r.get("name"),
            pseudonym=r.get("pseudonym"),
            dedup_hash=h,
            raw=r,
        )
        db.add(t)
        new += 1
    return {"new": new, "skipped": skipped, "total": len(rows)}


def persist_activity(db: Session, address: str, rows: list[dict]) -> dict:
    address = normalize_address(address)
    seen: set[str] = set()
    new = skipped = 0
    for r in rows:
        h = dedup_hash(
            r.get("transactionHash"), r.get("type"), r.get("asset"), r.get("side"),
            r.get("outcome"), r.get("price"), r.get("size"), r.get("usdcSize"), r.get("timestamp"),
        )
        exists = h in seen or db.scalar(
            select(models.WalletActivity.id).where(
                models.WalletActivity.wallet_address == address,
                models.WalletActivity.dedup_hash == h,
            )
        )
        if exists:
            skipped += 1
            continue
        seen.add(h)
        ts = r.get("timestamp")
        db.add(models.WalletActivity(
            wallet_address=address,
            type=(r.get("type") or "").upper() or None,
            condition_id=r.get("conditionId"),
            asset=str(r.get("asset")) if r.get("asset") is not None else None,
            side=(r.get("side") or "").upper() or None,
            outcome=r.get("outcome"),
            outcome_index=r.get("outcomeIndex"),
            price=to_float(r.get("price")),
            size=to_float(r.get("size")),
            usdc_size=to_float(r.get("usdcSize")),
            timestamp_epoch=int(ts) if ts is not None else None,
            ts_utc=epoch_to_utc(ts),
            transaction_hash=r.get("transactionHash"),
            slug=r.get("slug"),
            title=r.get("title"),
            dedup_hash=h,
            raw=r,
        ))
        new += 1
    return {"new": new, "skipped": skipped, "total": len(rows)}


def persist_positions(db: Session, address: str, rows: list[dict], value: float) -> dict:
    """Upsert current open positions (one row per position) + snapshot resolved ones as closed."""
    address = normalize_address(address)
    w = _ensure_wallet(db, address)
    fetched = now_utc()
    open_n = closed_n = 0
    closed_seen: set[str] = set()
    # Replace the open-position snapshot for this wallet (current holdings only).
    for old in db.scalars(select(models.WalletPosition).where(models.WalletPosition.wallet_address == address)):
        db.delete(old)
    for r in rows:
        end_date = parse_any_time(r.get("endDate"))
        redeemable = bool(r.get("redeemable"))
        db.add(models.WalletPosition(
            wallet_address=address,
            condition_id=r.get("conditionId"),
            asset=str(r.get("asset")) if r.get("asset") is not None else None,
            event_id=str(r.get("eventId")) if r.get("eventId") is not None else None,
            event_slug=r.get("eventSlug"),
            slug=r.get("slug"),
            title=r.get("title"),
            outcome=r.get("outcome"),
            outcome_index=r.get("outcomeIndex"),
            size=to_float(r.get("size")),
            avg_price=to_float(r.get("avgPrice")),
            cur_price=to_float(r.get("curPrice")),
            initial_value=to_float(r.get("initialValue")),
            current_value=to_float(r.get("currentValue")),
            cash_pnl=to_float(r.get("cashPnl")),
            realized_pnl=to_float(r.get("realizedPnl")),
            percent_pnl=to_float(r.get("percentPnl")),
            percent_realized_pnl=to_float(r.get("percentRealizedPnl")),
            total_bought=to_float(r.get("totalBought")),
            redeemable=redeemable,
            mergeable=bool(r.get("mergeable")) if r.get("mergeable") is not None else None,
            negative_risk=bool(r.get("negativeRisk")) if r.get("negativeRisk") is not None else None,
            end_date=end_date,
            fetched_at=fetched,
            raw=r,
        ))
        open_n += 1
        # Resolved / redeemable -> also persist into closed positions (idempotent).
        if redeemable or (end_date is not None and end_date < fetched):
            h = dedup_hash(address, r.get("conditionId"), r.get("asset"), r.get("realizedPnl"))
            if h not in closed_seen and not db.scalar(select(models.WalletClosedPosition.id).where(
                models.WalletClosedPosition.wallet_address == address,
                models.WalletClosedPosition.dedup_hash == h,
            )):
                closed_seen.add(h)
                db.add(models.WalletClosedPosition(
                    wallet_address=address,
                    condition_id=r.get("conditionId"),
                    asset=str(r.get("asset")) if r.get("asset") is not None else None,
                    slug=r.get("slug"),
                    title=r.get("title"),
                    outcome=r.get("outcome"),
                    outcome_index=r.get("outcomeIndex"),
                    size=to_float(r.get("size")),
                    avg_price=to_float(r.get("avgPrice")),
                    realized_pnl=to_float(r.get("realizedPnl")),
                    percent_realized_pnl=to_float(r.get("percentRealizedPnl")),
                    total_bought=to_float(r.get("totalBought")),
                    end_date=end_date,
                    fetched_at=fetched,
                    dedup_hash=h,
                    raw=r,
                ))
                closed_n += 1
    w.last_synced_at = fetched
    return {"open": open_n, "closed_snapshotted": closed_n, "portfolio_value": value}


def persist_wallet(db: Session, address: str, data: dict) -> dict:
    address = normalize_address(address)
    if data["trades"]:
        persist_profile(db, address, data["trades"][0])
    t = persist_trades(db, address, data["trades"])
    a = persist_activity(db, address, data["activity"])
    p = persist_positions(db, address, data["positions"], data["value"])
    return {"trades": t, "activity": a, "positions": p}


async def sync_wallet(address: str | None = None, *, max_pages: int = 50, db: Session | None = None) -> dict:
    address = normalize_address(address or settings.target_wallet)
    data = await fetch_wallet(address, max_pages=max_pages)
    if db is not None:
        summary = persist_wallet(db, address, data)
        db.commit()
    else:
        with session_scope() as s:
            summary = persist_wallet(s, address, data)
    _record_last_sync(address, summary)
    log.info("wallet_sync_done", address=address,
             trades_new=summary["trades"]["new"], activity_new=summary["activity"]["new"])
    return summary


def _record_last_sync(address: str, summary: dict) -> None:
    try:
        with session_scope() as db:
            setting = db.get(models.AppSetting, "last_wallet_sync_at")
            if setting is None:
                setting = models.AppSetting(key="last_wallet_sync_at")
                db.add(setting)
            setting.value = {"at": now_utc().isoformat(), "address": address, "summary": summary}
            setting.updated_at = now_utc()
    except Exception as exc:  # pragma: no cover
        log.debug("record_last_sync_failed", error=str(exc))
