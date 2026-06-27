"""Market parser tests (slug/title grammar, status, resolution, uncertainty)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.parsing import looks_like_crypto_updown, parse_market
from tests.conftest import load_fixture

UTC = timezone.utc


def test_parse_real_event_market_fixture():
    market = load_fixture("gamma_market_updown.json")
    event = load_fixture("gamma_event_crypto_updown.json")[0]
    p = parse_market(market, event)
    assert p.asset_symbol == "HYPE"
    assert p.window_minutes == 5
    assert p.outcomes == ["Up", "Down"]
    assert p.up_token_id and p.down_token_id
    assert p.up_token_id != p.down_token_id
    assert p.is_crypto_updown is True
    assert p.parse_status == "ok"


def test_slug_grammar_assets_and_windows():
    cases = {
        "btc-updown-15m-1782149400": ("BTC", 15),
        "xrp-updown-5m-1782287100": ("XRP", 5),
        "doge-updown-15m-1782287100": ("DOGE", 15),
        "eth-updown-5m-1700000000": ("ETH", 5),
    }
    for slug, (asset, win) in cases.items():
        p = parse_market({"slug": slug, "outcomes": ["Up", "Down"],
                          "clobTokenIds": ["a", "b"], "closed": False})
        assert p.asset_symbol == asset
        assert p.window_minutes == win
        assert p.up_token_id == "a" and p.down_token_id == "b"


def test_resolution_from_outcome_prices():
    raw = {"slug": "btc-updown-5m-1700000000", "outcomes": ["Up", "Down"],
           "clobTokenIds": ["a", "b"], "closed": True, "outcomePrices": ["1", "0"]}
    p = parse_market(raw)
    assert p.resolved_outcome == "Up"
    assert p.status == "resolved"

    raw["outcomePrices"] = ["0", "1"]
    assert parse_market(raw).resolved_outcome == "Down"


def test_status_upcoming_live_ended():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    start = int(datetime(2026, 6, 1, 12, 10, tzinfo=UTC).timestamp())  # future
    up = parse_market({"slug": f"btc-updown-5m-{start}", "outcomes": ["Up", "Down"],
                       "clobTokenIds": ["a", "b"]}, now=now)
    assert up.status == "upcoming"

    live_start = int(datetime(2026, 6, 1, 11, 58, tzinfo=UTC).timestamp())  # 2 min ago, 5m window
    live = parse_market({"slug": f"btc-updown-5m-{live_start}", "outcomes": ["Up", "Down"],
                         "clobTokenIds": ["a", "b"], "active": True, "acceptingOrders": True},
                        now=now)
    assert live.status == "live"


def test_uncertain_when_asset_unknown():
    p = parse_market({"slug": "weird-market-xyz", "question": "Something?",
                      "outcomes": ["Yes", "No"], "clobTokenIds": ["a", "b"]})
    assert p.parse_status == "uncertain"
    assert p.parse_notes is not None


def test_slug_time_authoritative_over_gamma():
    """Regression (audit #1): the slug window start wins; Gamma's listing startDate and its
    frequently-wrong-day endDate must NOT corrupt start_time/end_time."""
    slug_ts = 1782207300  # aligned 5m boundary
    raw = {
        "slug": f"btc-updown-5m-{slug_ts}", "outcomes": ["Up", "Down"],
        "clobTokenIds": ["a", "b"],
        "startDate": "2026-06-23T08:53:05Z",   # listing time (garbage for the window)
        "endDate": "2026-06-24T08:50:00Z",      # NEXT DAY (garbage)
    }
    p = parse_market(raw)
    assert p.start_epoch == slug_ts
    assert int(p.end_time.timestamp()) == slug_ts + 300       # slug-derived end, not Gamma's
    assert (p.end_time - p.start_time).total_seconds() == 300  # exactly the 5-minute window


def test_long_dated_window_flagged_uncertain():
    """Regression (audit #5): a long-dated crypto market caught by the title heuristic infers a
    multi-hour window and must be flagged uncertain (so it's excluded from the 5m/15m universe)."""
    raw = {
        "slug": "bitcoin-up-or-down-june-25-2026-5am-et", "question": "Bitcoin Up or Down?",
        "outcomes": ["Up", "Down"], "clobTokenIds": ["a", "b"],
        "startDate": "2026-06-25T00:00:00Z", "endDate": "2026-06-25T05:00:00Z",
    }
    p = parse_market(raw)
    assert p.window_minutes is not None and p.window_minutes > 60
    assert p.parse_status == "uncertain"


def test_looks_like_crypto_updown_by_title_outcomes():
    assert looks_like_crypto_updown(
        {"slug": "x", "question": "Bitcoin Up or Down?", "outcomes": ["Up", "Down"]})
    assert not looks_like_crypto_updown(
        {"slug": "election-2028", "question": "Who wins?", "outcomes": ["A", "B"]})
