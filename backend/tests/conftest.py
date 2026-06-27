"""Test fixtures. Offline by default — a temp SQLite DB + synthetic factories + canned JSON.

Setting PML_DATABASE_URL before importing app binds the global engine to a throwaway file,
so services that use session_scope() internally also hit the test DB.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "pml_test.db"
os.environ["PML_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.setdefault("PML_ENABLE_RTDS", "false")

import pytest  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.db import models  # noqa: E402

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(_TMP_DB) + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            s.execute(table.delete())
        s.commit()
        s.close()


# --------------------------------------------------------------------------- factories


@pytest.fixture
def make_market(db):
    counter = {"n": 0}

    def _make(*, asset="BTC", window=5, start=None, resolved="Up",
              up_token=None, down_token=None, fee_schedule=None, enable_book=True,
              last_trade_price=0.5, status="resolved"):
        counter["n"] += 1
        i = counter["n"]
        start = start or datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        up_token = up_token or f"UP{i}"
        down_token = down_token or f"DN{i}"
        m = models.Market(
            gamma_market_id=str(1000 + i), condition_id=f"0xcond{i}",
            slug=f"{asset.lower()}-updown-{window}m-{int(start.timestamp())}-{i}",
            title=f"{asset} Up or Down #{i}", asset_symbol=asset, window_minutes=window,
            start_time=start, end_time=start + timedelta(minutes=window),
            start_epoch=int(start.timestamp()), end_epoch=int((start + timedelta(minutes=window)).timestamp()),
            outcomes=["Up", "Down"], clob_token_ids=[up_token, down_token],
            up_token_id=up_token, down_token_id=down_token, enable_order_book=enable_book,
            fee_schedule=fee_schedule or {"exponent": 1, "rate": 0.07, "takerOnly": True, "rebateRate": 0.2},
            last_trade_price=last_trade_price, status=status, parse_status="ok",
            resolved_outcome=resolved, closed=(status in ("resolved", "ended")),
        )
        db.add(m)
        db.flush()
        for idx, (name, tok) in enumerate([("Up", up_token), ("Down", down_token)]):
            db.add(models.MarketOutcome(market_id=m.id, outcome_index=idx, outcome_name=name,
                                        token_id=tok, is_winner=(name == resolved)))
        db.flush()
        return m

    return _make


@pytest.fixture
def make_trade(db):
    def _make(market, *, side="BUY", outcome="Up", price=0.5, size=100.0,
              wallet="0xtarget", ts=None, token=None):
        ts = ts or market.start_time + timedelta(seconds=30)
        tok = token or (market.up_token_id if outcome == "Up" else market.down_token_id)
        t = models.Trade(
            wallet_address=wallet.lower(), condition_id=market.condition_id, asset=tok,
            market_id=market.id, slug=market.slug, side=side, outcome=outcome,
            price=price, size=size, notional=price * size,
            timestamp_epoch=int(ts.timestamp()), ts_utc=ts,
            transaction_hash=f"0xtx{int(ts.timestamp())}{outcome}{price}",
            dedup_hash=f"h{market.id}{side}{outcome}{price}{size}{int(ts.timestamp())}",
        )
        db.add(t)
        db.flush()
        return t

    return _make


@pytest.fixture
def make_snapshot(db):
    def _make(token, *, ts, best_bid=0.49, best_ask=0.51, source="clob_ws", accepted=True):
        s = models.OrderbookSnapshot(
            token_id=token, source=source, received_ts=ts, best_bid=best_bid, best_ask=best_ask,
            mid=(best_bid + best_ask) / 2, spread=best_ask - best_bid,
            bid_depth_top5=500.0, ask_depth_top5=400.0, accepted=accepted)
        db.add(s)
        db.flush()
        return s

    return _make


@pytest.fixture
def make_tick(db):
    def _make(asset, *, ts, price, source="binance"):
        t = models.CryptoPriceTick(asset_symbol=asset, source=source, price=price,
                                   source_ts=ts, received_ts=ts, accepted=True)
        db.add(t)
        db.flush()
        return t

    return _make
