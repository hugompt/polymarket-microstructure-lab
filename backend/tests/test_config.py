"""Config env-parsing regression tests.

pydantic-settings JSON-parses list[str] env vars by default, which rejects the comma-separated
values documented in .env.example (e.g. PML_ASSETS=BTC,ETH). The NoDecode annotation must let the
raw string reach the CSV-splitting validators.
"""
from __future__ import annotations

from app.config import Settings


def test_assets_and_windows_from_csv_env(monkeypatch):
    monkeypatch.setenv("PML_ASSETS", "BTC,ETH,SOL")
    monkeypatch.setenv("PML_WINDOWS_MINUTES", "5,15")
    s = Settings()
    assert s.assets == ["BTC", "ETH", "SOL"]
    assert s.windows_minutes == [5, 15]


def test_cors_origins_csv_and_wildcard(monkeypatch):
    monkeypatch.setenv("PML_CORS_ALLOW_ORIGINS", "http://localhost:3000,http://example.com")
    assert Settings().cors_allow_origins == ["http://localhost:3000", "http://example.com"]
    monkeypatch.setenv("PML_CORS_ALLOW_ORIGINS", "*")
    assert Settings().cors_allow_origins == ["*"]


def test_list_defaults_when_unset(monkeypatch):
    for k in ("PML_ASSETS", "PML_WINDOWS_MINUTES", "PML_CORS_ALLOW_ORIGINS"):
        monkeypatch.delenv(k, raising=False)
    s = Settings()
    assert s.assets == ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    assert s.windows_minutes == [5, 15]
