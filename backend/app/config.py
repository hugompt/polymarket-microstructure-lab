"""Application configuration.

All settings are read from environment variables / .env (pydantic-settings).
NOTHING here enables trading. There are deliberately no private-key, auth-signing,
or order-placement settings. This project is read-only by construction.

All time handling in the app is UTC. See app.util.time helpers.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_prefix="PML_",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_name: str = "polymarket-microstructure-lab"
    environment: str = "local"
    log_level: str = "INFO"
    log_json: bool = False  # pretty console logs locally; set true for structured JSON

    # ---- Database ----
    # SQLite fallback for quick local testing; Postgres for normal usage.
    database_url: str = "sqlite:///./polymarket_lab.db"

    # ---- Polymarket public read-only endpoints (source of truth: docs.polymarket.com) ----
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    data_base_url: str = "https://data-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    # CLOB public market websocket channel (orderbook / price_change / last_trade_price).
    clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    # RTDS / real-time crypto price websocket. Endpoint may evolve; client is tolerant
    # and logs unknown messages instead of crashing. Binance is used as a robust fallback.
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    binance_ws_url: str = "wss://stream.binance.com:9443/stream"
    enable_rtds: bool = True
    enable_binance_fallback: bool = True

    http_user_agent: str = "polymarket-microstructure-lab/0.1 (read-only research)"
    http_timeout_seconds: float = 25.0

    # CORS origins allowed to call the API (the dashboard). Comma-separated env override.
    # NoDecode: let the raw env string reach the validator (don't JSON-parse it first).
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # ---- Rate limiting / reliability (respect public API limits) ----
    # Conservative token-bucket per host. Tune via env, never hammer.
    rate_limit_per_sec: float = 5.0
    rate_limit_burst: int = 10
    max_retries: int = 4
    backoff_base_seconds: float = 0.5
    backoff_cap_seconds: float = 20.0
    # Hard ceiling on total outbound requests per process run (safety budget).
    request_budget: int = 50_000

    # ---- Target wallet ----
    # REQUIRED for wallet analysis: the PUBLIC on-chain address of the bot to investigate.
    # Set PML_TARGET_WALLET (and optional PML_TARGET_PROFILE label) in your .env, or pass
    # --wallet on the CLI. This is public data only and must NEVER be a private key/seed.
    # Empty by default so the repo ships with no specific wallet baked in.
    target_wallet: str = ""
    target_profile: str = ""

    # ---- Universe (configurable) ----
    # Asset symbols as they appear in market slugs ("btc-updown-5m-...").
    # NoDecode so PML_ASSETS / PML_WINDOWS_MINUTES can be plain comma-separated env strings
    # (pydantic-settings would otherwise JSON-parse list fields and reject "BTC,ETH").
    assets: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    windows_minutes: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [5, 15])

    # ---- Collector ----
    # Default conservative: do NOT default to abusive 100-300 connections.
    ws_max_connections: int = 2
    # Collect only markets that are live now or start within this many minutes. Polymarket
    # pre-lists markets ~19h ahead, so collecting all "upcoming" would subscribe hundreds of
    # tokens per WS connection and the server drops the oversized subscription (reconnect storm).
    collector_lead_minutes: int = 20
    collector_poll_seconds: float = 5.0          # CLOB /book polling validator cadence
    discovery_poll_seconds: float = 30.0
    wallet_sync_poll_seconds: float = 60.0

    # ---- Data quality thresholds ----
    stale_after_seconds: float = 30.0            # snapshot older than this => stale
    max_price_jump: float = 0.5                  # |Δprice| above this on a tick => flagged impossible
    reconnect_grace_seconds: float = 3.0         # suspect first ticks within this window post-reconnect

    # ---- Fee model fallbacks (used only when market metadata lacks a schedule) ----
    # Polymarket binary markets historically charge fees on the "winnings" side.
    # These are FALLBACKS; real schedule from market metadata is preferred. Never a hardcoded
    # break-even: break-even is always computed dynamically from price + fees + spread.
    fallback_taker_fee_rate: float = 0.0         # fraction of notional / per formula
    fallback_maker_fee_rate: float = 0.0
    fallback_fee_rate: float = 0.02              # used by the "conservative" sensitivity scenario

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _v_cors(cls, v):
        out = _split_csv(v)
        return out or ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("assets", mode="before")
    @classmethod
    def _v_assets(cls, v):
        out = [a.upper() for a in _split_csv(v)]
        return out or ["BTC", "ETH", "SOL", "XRP", "DOGE"]

    @field_validator("windows_minutes", mode="before")
    @classmethod
    def _v_windows(cls, v):
        if isinstance(v, (list, tuple)):
            items = v
        else:
            items = _split_csv(v)
        out = []
        for x in items:
            try:
                out.append(int(str(x).replace("m", "").strip()))
            except (TypeError, ValueError):
                continue
        return out or [5, 15]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
