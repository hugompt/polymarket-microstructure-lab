"""Discovery persistence + wallet-sync dedup (offline, using captured API fixtures)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.db import models
from app.services.discovery import persist_markets
from app.services.wallet_sync import persist_activity, persist_trades
from tests.conftest import load_fixture


def test_persist_markets_from_event_fixture(db):
    event = load_fixture("gamma_event_crypto_updown.json")[0]
    pairs = [(m, event) for m in event.get("markets", [])]
    summary = persist_markets(db, pairs)
    db.commit()
    assert summary["total"] == len(pairs)
    assert summary["new"] == len(pairs)
    m = db.scalar(select(models.Market))
    assert m.asset_symbol == "HYPE"
    assert m.window_minutes == 5
    assert m.up_token_id and m.down_token_id
    assert len(m.outcomes_rel) == 2


def test_persist_markets_is_idempotent(db):
    event = load_fixture("gamma_event_crypto_updown.json")[0]
    pairs = [(m, event) for m in event.get("markets", [])]
    persist_markets(db, pairs)
    db.commit()
    summary2 = persist_markets(db, pairs)
    db.commit()
    assert summary2["new"] == 0
    assert summary2["updated"] == len(pairs)
    assert db.scalar(select(func.count()).select_from(models.Market)) == len(pairs)


def test_persist_trades_dedup(db):
    trades = load_fixture("data_trades.json")
    wallet = "0x000000000000000000000000000000000000dEaD"
    first = persist_trades(db, wallet, trades)
    db.commit()
    assert first["new"] == len(trades)
    # second run: everything is a duplicate
    second = persist_trades(db, wallet, trades)
    db.commit()
    assert second["new"] == 0
    assert second["skipped"] == len(trades)
    assert db.scalar(select(func.count()).select_from(models.Trade)) == len(trades)


def test_persist_trades_intrabatch_duplicate(db):
    """Two identical rows in ONE batch must not violate the unique constraint."""
    trades = load_fixture("data_trades.json")
    dupe_batch = trades + [trades[0]]  # inject an intra-batch duplicate
    res = persist_trades(db, "0xwallet", dupe_batch)
    db.commit()
    assert res["new"] == len(trades)
    assert res["skipped"] == 1


def test_persist_activity_dedup(db):
    activity = load_fixture("data_activity.json")
    res = persist_activity(db, "0xwallet", activity)
    db.commit()
    assert res["new"] == len(activity)
    res2 = persist_activity(db, "0xwallet", activity)
    db.commit()
    assert res2["new"] == 0
