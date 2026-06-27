"""Relational schema for the microstructure lab.

Design notes
------------
* Every externally-sourced row keeps a ``raw`` JSON column = the verbatim API payload,
  so analysis is reproducible and schema drift never loses data (rules 11 & "store
  unknown fields").
* Prices are 0..1 probabilities; sizes are share counts. Float is sufficient and portable.
* Times: ``*_utc`` columns are tz-aware UTC datetimes; ``*_epoch`` columns keep the exact
  integer epoch seconds the API returned, for lossless reproduction (rule 10).
* PnL accounting is kept strictly separated: API-reported vs reconstructed vs estimated
  vs portfolio value (rule "never confuse balance with profit").
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BigInt, Base, JSONType, TimestampMixin, UTCDateTime

# --------------------------------------------------------------------------------------
# Settings / KV (collector state persistence so restarts keep continuity)
# --------------------------------------------------------------------------------------


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# --------------------------------------------------------------------------------------
# Wallets
# --------------------------------------------------------------------------------------


class Wallet(Base, TimestampMixin):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_target: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    profiles: Mapped[list["WalletProfile"]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan"
    )


class WalletProfile(Base, TimestampMixin):
    __tablename__ = "wallet_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    address: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pseudonym: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    wallet: Mapped[Wallet] = relationship(back_populates="profiles")


# --------------------------------------------------------------------------------------
# Markets
# --------------------------------------------------------------------------------------


class Market(Base, TimestampMixin):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gamma_market_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_id: Mapped[str | None] = mapped_column(String(64), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True)
    question_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(160), index=True)
    event_slug: Mapped[str | None] = mapped_column(String(160), index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset_symbol: Mapped[str | None] = mapped_column(String(16), index=True)
    window_minutes: Mapped[int | None] = mapped_column(Integer, index=True)

    start_time: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    start_epoch: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    end_epoch: Mapped[int | None] = mapped_column(BigInt, nullable=True)

    outcomes: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    clob_token_ids: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    up_token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    down_token_id: Mapped[str | None] = mapped_column(String(96), index=True)

    enable_order_book: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accepting_orders: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    closed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    archived: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Fees / rewards (verbatim where present; never used to hardcode break-even).
    fee_schedule: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    fee_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fees_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    maker_base_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    taker_base_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    rewards_min_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    rewards_max_spread: Mapped[float | None] = mapped_column(Float, nullable=True)

    neg_risk: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_min_size: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Discovery-time snapshot of top-of-book (Gamma fields).
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # upcoming | live | ended | resolved | unknown
    status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    # ok | uncertain
    parse_status: Mapped[str] = mapped_column(String(16), default="ok")
    parse_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    resolved_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolution_payouts: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    outcomes_rel: Mapped[list["MarketOutcome"]] = relationship(
        back_populates="market", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("condition_id", name="uq_markets_condition_id"),
        Index("ix_markets_asset_window", "asset_symbol", "window_minutes"),
        Index("ix_markets_status_start", "status", "start_time"),
    )


class MarketOutcome(Base, TimestampMixin):
    __tablename__ = "market_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome_index: Mapped[int] = mapped_column(Integer)
    outcome_name: Mapped[str | None] = mapped_column(String(32))  # Up / Down
    token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_winner: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    market: Mapped[Market] = relationship(back_populates="outcomes_rel")

    __table_args__ = (
        UniqueConstraint("market_id", "outcome_index", name="uq_outcome_market_idx"),
    )


# --------------------------------------------------------------------------------------
# Market microstructure data: raw vs clean event log + structured orderbook
# --------------------------------------------------------------------------------------


class MarketSnapshotRaw(Base):
    """Every event received from any feed, verbatim. Append-only."""

    __tablename__ = "market_snapshots_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    source: Mapped[str] = mapped_column(String(32))  # clob_ws | clob_rest | rtds | binance
    event_type: Mapped[str | None] = mapped_column(String(32))  # book | price_change | ...
    source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    processing_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    dedup_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class MarketSnapshotClean(Base):
    """Accepted / cleaned events with quality flags. Mirrors raw 1:1 for accepted rows."""

    __tablename__ = "market_snapshots_clean"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_id: Mapped[int | None] = mapped_column(ForeignKey("market_snapshots_raw.id"), index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    source: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str | None] = mapped_column(String(32))
    source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_out_of_order: Mapped[bool] = mapped_column(Boolean, default=False)


class OrderbookSnapshot(Base):
    """Normalised top-of-book + depth at a point in time (the primary backtest input)."""

    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    outcome_name: Mapped[str | None] = mapped_column(String(16))  # Up / Down
    source: Mapped[str] = mapped_column(String(32))
    source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_depth_top5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_depth_top5: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_depth_top10: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_depth_top10: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    book_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_out_of_order: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    levels: Mapped[list["OrderbookLevel"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_book_token_recv", "token_id", "received_ts"),)


class OrderbookLevel(Base):
    __tablename__ = "orderbook_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("orderbook_snapshots.id"), index=True)
    side: Mapped[str] = mapped_column(String(4))  # bid | ask
    level_index: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)

    snapshot: Mapped[OrderbookSnapshot] = relationship(back_populates="levels")


class CryptoPriceTick(Base):
    """Spot crypto ticks (RTDS Binance/Chainlink, or direct Binance fallback)."""

    __tablename__ = "crypto_price_ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_symbol: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(24))  # binance | chainlink | rtds
    price: Mapped[float] = mapped_column(Float)
    source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    received_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_out_of_order: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (Index("ix_tick_asset_src_ts", "asset_symbol", "source", "source_ts"),)


# --------------------------------------------------------------------------------------
# Wallet activity: trades / activity / positions / closed positions
# --------------------------------------------------------------------------------------


class Trade(Base, TimestampMixin):
    """A fill from the Data API /trades endpoint for a tracked wallet."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    proxy_wallet: Mapped[str | None] = mapped_column(String(64), nullable=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True)
    asset: Mapped[str | None] = mapped_column(String(96), index=True)  # token id
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    event_slug: Mapped[str | None] = mapped_column(String(160), index=True)
    slug: Mapped[str | None] = mapped_column(String(160), index=True)
    side: Mapped[str | None] = mapped_column(String(8))  # BUY | SELL
    outcome: Mapped[str | None] = mapped_column(String(32))
    outcome_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    notional: Mapped[float | None] = mapped_column(Float)
    timestamp_epoch: Mapped[int | None] = mapped_column(BigInt, index=True)
    ts_utc: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    transaction_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pseudonym: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    enrichment: Mapped["WalletTradeEnrichment | None"] = relationship(
        back_populates="trade", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("wallet_address", "dedup_hash", name="uq_trade_wallet_dedup"),
        Index("ix_trades_wallet_ts", "wallet_address", "ts_utc"),
    )


class WalletActivity(Base, TimestampMixin):
    """Data API /activity rows (TRADE / REDEEM / REWARD / SPLIT / MERGE / ...)."""

    __tablename__ = "wallet_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str | None] = mapped_column(String(24), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True)
    asset: Mapped[str | None] = mapped_column(String(96), index=True)
    side: Mapped[str | None] = mapped_column(String(8))
    outcome: Mapped[str | None] = mapped_column(String(32))
    outcome_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    usdc_size: Mapped[float | None] = mapped_column(Float)
    timestamp_epoch: Mapped[int | None] = mapped_column(BigInt, index=True)
    ts_utc: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    transaction_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    slug: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        UniqueConstraint("wallet_address", "dedup_hash", name="uq_activity_wallet_dedup"),
    )


class WalletPosition(Base, TimestampMixin):
    """Open-position snapshot from Data API /positions (kept with fetched_at for history)."""

    __tablename__ = "wallet_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True)
    asset: Mapped[str | None] = mapped_column(String(96), index=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_slug: Mapped[str | None] = mapped_column(String(160), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32))
    outcome_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[float | None] = mapped_column(Float)
    avg_price: Mapped[float | None] = mapped_column(Float)
    cur_price: Mapped[float | None] = mapped_column(Float)
    initial_value: Mapped[float | None] = mapped_column(Float)
    current_value: Mapped[float | None] = mapped_column(Float)
    cash_pnl: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    percent_pnl: Mapped[float | None] = mapped_column(Float)
    percent_realized_pnl: Mapped[float | None] = mapped_column(Float)
    total_bought: Mapped[float | None] = mapped_column(Float)
    redeemable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mergeable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    negative_risk: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class WalletClosedPosition(Base, TimestampMixin):
    """Resolved / closed positions (realized PnL is final here)."""

    __tablename__ = "wallet_closed_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True)
    asset: Mapped[str | None] = mapped_column(String(96), index=True)
    slug: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32))
    outcome_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[float | None] = mapped_column(Float)
    avg_price: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    percent_realized_pnl: Mapped[float | None] = mapped_column(Float)
    total_bought: Mapped[float | None] = mapped_column(Float)
    end_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        UniqueConstraint("wallet_address", "dedup_hash", name="uq_closed_wallet_dedup"),
    )


class WalletTradeEnrichment(Base, TimestampMixin):
    """Microstructure context attached to each wallet trade (nearest book/ticks, phase...)."""

    __tablename__ = "wallet_trade_enrichments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), unique=True, index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    asset_symbol: Mapped[str | None] = mapped_column(String(16), index=True)
    window_minutes: Mapped[int | None] = mapped_column(Integer, index=True)
    seconds_since_open: Mapped[float | None] = mapped_column(Float)
    seconds_until_close: Mapped[float | None] = mapped_column(Float)
    market_phase: Mapped[str | None] = mapped_column(String(16))  # open | mid | close
    entry_price_bucket: Mapped[str | None] = mapped_column(String(16), index=True)
    spread_at_entry: Mapped[float | None] = mapped_column(Float)
    depth_at_entry: Mapped[float | None] = mapped_column(Float)
    nearest_book_before_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nearest_book_after_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    binance_before_price: Mapped[float | None] = mapped_column(Float)
    binance_after_price: Mapped[float | None] = mapped_column(Float)
    chainlink_before_price: Mapped[float | None] = mapped_column(Float)
    chainlink_after_price: Mapped[float | None] = mapped_column(Float)
    breakeven_winrate: Mapped[float | None] = mapped_column(Float)
    ev_per_share: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    trade: Mapped[Trade] = relationship(back_populates="enrichment")


# --------------------------------------------------------------------------------------
# Data quality + feed health + API call logs
# --------------------------------------------------------------------------------------


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    asset_symbol: Mapped[str | None] = mapped_column(String(16), index=True)
    source: Mapped[str | None] = mapped_column(String(32))
    # stale | duplicate | out_of_order | impossible_jump | gap | reconnect | rejected | ...
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(12), default="warn")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class FeedHealth(Base):
    """Rolling per-(source, token/asset) health, persisted so restarts keep continuity."""

    __tablename__ = "feed_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    token_id: Mapped[str | None] = mapped_column(String(96), index=True)
    asset_symbol: Mapped[str | None] = mapped_column(String(16), index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    messages: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    stale: Mapped[int] = mapped_column(Integer, default=0)
    out_of_order: Mapped[int] = mapped_column(Integer, default=0)
    gaps: Mapped[int] = mapped_column(Integer, default=0)
    reconnects: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("source", "token_id", "asset_symbol", name="uq_feed_health_key"),
    )


class ApiCallLog(Base):
    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    client: Mapped[str | None] = mapped_column(String(24), index=True)  # gamma|data|clob
    method: Mapped[str] = mapped_column(String(8))
    host: Mapped[str | None] = mapped_column(String(96), index=True)
    path: Mapped[str | None] = mapped_column(String(256))
    query: Mapped[str | None] = mapped_column(Text)  # sanitised
    status_code: Mapped[int | None] = mapped_column(Integer, index=True)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)


# --------------------------------------------------------------------------------------
# Strategy lab
# --------------------------------------------------------------------------------------


class StrategyRun(Base, TimestampMixin):
    __tablename__ = "strategy_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_key: Mapped[str] = mapped_column(String(48), index=True)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    assets: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    windows: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    date_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    date_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    fill_model: Mapped[str | None] = mapped_column(String(24))
    fee_scenario: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="done", index=True)
    n_markets: Mapped[int | None] = mapped_column(Integer)
    n_attempts: Mapped[int | None] = mapped_column(Integer)
    n_filled: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    trades: Mapped[list["StrategyRunTrade"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    metrics: Mapped["StrategyRunMetric | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class StrategyRunTrade(Base):
    __tablename__ = "strategy_run_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("strategy_runs.id"), index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    asset_symbol: Mapped[str | None] = mapped_column(String(16), index=True)
    window_minutes: Mapped[int | None] = mapped_column(Integer, index=True)
    outcome_chosen: Mapped[str | None] = mapped_column(String(16))
    intended_ts: Mapped[datetime | None] = mapped_column(UTCDateTime)
    intended_price: Mapped[float | None] = mapped_column(Float)
    filled: Mapped[bool] = mapped_column(Boolean, default=False)
    fill_price: Mapped[float | None] = mapped_column(Float)
    fill_ts: Mapped[datetime | None] = mapped_column(UTCDateTime)
    size: Mapped[float | None] = mapped_column(Float)
    fees: Mapped[float | None] = mapped_column(Float)
    spread_cost: Mapped[float | None] = mapped_column(Float)
    slippage: Mapped[float | None] = mapped_column(Float)
    resolved_outcome: Mapped[str | None] = mapped_column(String(16))
    won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float)
    hour_utc: Mapped[int | None] = mapped_column(Integer, index=True)
    is_weekend: Mapped[bool | None] = mapped_column(Boolean)
    entry_price_bucket: Mapped[str | None] = mapped_column(String(16))
    reason_unfilled: Mapped[str | None] = mapped_column(String(48))
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    run: Mapped[StrategyRun] = relationship(back_populates="trades")


class StrategyRunMetric(Base):
    __tablename__ = "strategy_run_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("strategy_runs.id"), unique=True, index=True)
    n_markets: Mapped[int | None] = mapped_column(Integer)
    n_attempts: Mapped[int | None] = mapped_column(Integer)
    n_filled: Mapped[int | None] = mapped_column(Integer)
    fill_rate: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    avg_entry_price: Mapped[float | None] = mapped_column(Float)
    avg_exit_value: Mapped[float | None] = mapped_column(Float)
    gross_pnl: Mapped[float | None] = mapped_column(Float)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    sharpe_like: Mapped[float | None] = mapped_column(Float)
    vs_random_net_pnl: Mapped[float | None] = mapped_column(Float)
    sample_warning: Mapped[bool | None] = mapped_column(Boolean, default=False)
    breakdowns: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    full: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    run: Mapped[StrategyRun] = relationship(back_populates="metrics")


# --------------------------------------------------------------------------------------
# Forward (live) paper trading — SIMULATED orders against LIVE markets. NO real orders.
# A single decision stream feeds N "latency accounts"; each fills at its own latency against
# the book as it has moved during the order's flight, then settles on the real resolution.
# --------------------------------------------------------------------------------------


class PaperSession(Base, TimestampMixin):
    __tablename__ = "paper_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_key: Mapped[str] = mapped_column(String(48), index=True)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    assets: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    windows: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    latency_grid_ms: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    size: Mapped[float | None] = mapped_column(Float)
    fill_model: Mapped[str | None] = mapped_column(String(24))
    fee_scenario: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    stopped_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    orders: Mapped[list["PaperOrder"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class PaperOrder(Base):
    """One simulated order per (decision, latency account). No real order is ever placed."""

    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"), index=True)
    decision_id: Mapped[str | None] = mapped_column(String(48), index=True)  # groups the accounts
    latency_ms: Mapped[int] = mapped_column(Integer, index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True)
    asset_symbol: Mapped[str | None] = mapped_column(String(16), index=True)
    window_minutes: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(16))

    decision_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    decision_price: Mapped[float | None] = mapped_column(Float)  # best ask at decision time
    decision_mid: Mapped[float | None] = mapped_column(Float)
    arrive_ts: Mapped[datetime | None] = mapped_column(UTCDateTime)  # decision_ts + latency

    filled: Mapped[bool] = mapped_column(Boolean, default=False)
    fill_price: Mapped[float | None] = mapped_column(Float)  # ask at arrival (adverse-selected)
    fill_size: Mapped[float | None] = mapped_column(Float)
    spread_cost: Mapped[float | None] = mapped_column(Float)
    slippage_vs_decision: Mapped[float | None] = mapped_column(Float)  # fill_price - decision_price
    fees: Mapped[float | None] = mapped_column(Float)

    # open | filled | missed | settled | expired
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    resolved_outcome: Mapped[str | None] = mapped_column(String(16))
    won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float)
    settle_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    session: Mapped[PaperSession] = relationship(back_populates="orders")

    __table_args__ = (Index("ix_paper_orders_session_latency", "session_id", "latency_ms"),)


class PaperAccountEquity(Base):
    """Periodic equity snapshot per latency account (for the equity curve)."""

    __tablename__ = "paper_account_equity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Float, default=0.0)
    n_decisions: Mapped[int] = mapped_column(Integer, default=0)
    n_filled: Mapped[int] = mapped_column(Integer, default=0)
    n_open: Mapped[int] = mapped_column(Integer, default=0)
    n_settled: Mapped[int] = mapped_column(Integer, default=0)
    n_won: Mapped[int] = mapped_column(Integer, default=0)
