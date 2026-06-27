# Internal API contract (backend ↔ frontend)

Base URL: `${NEXT_PUBLIC_API_BASE}` (default `http://localhost:8000`). All times are ISO-8601 UTC
strings unless suffixed `_epoch` (Unix seconds). Money/PnL in USDC. Prices are 0..1 probabilities.

The DB may be **empty** until collectors run — every endpoint returns valid empty shapes
(`[]`, `0`, `null`), never errors, so the dashboard must render graceful empty states.

## Health
`GET /api/health` →
```json
{
  "status": "ok",
  "time_utc": "2026-06-23T12:00:00Z",
  "db_ok": true,
  "request_budget_remaining": 49000,
  "counts": {"markets": 0, "live_markets": 0, "upcoming_markets": 0, "trades": 0,
             "orderbook_snapshots_today": 0, "ticks_today": 0, "api_errors_today": 0},
  "feeds": [{"source": "clob_ws", "connected": false, "last_message_age_s": null,
             "messages": 0, "duplicates": 0, "stale": 0, "out_of_order": 0, "reconnects": 0}],
  "last_discovery_at": null, "last_wallet_sync_at": null,
  "warnings": ["No live feeds connected", "..."]
}
```

## Markets
`GET /api/markets/live` and `GET /api/markets/upcoming` →
```json
{"markets": [{
  "id": 1, "slug": "btc-updown-5m-1782149400", "asset": "BTC", "window_minutes": 5,
  "title": "Bitcoin Up or Down ...", "status": "live",
  "start_time": "2026-06-23T...Z", "end_time": "2026-06-23T...Z", "seconds_to_close": 142,
  "up_price": 0.62, "down_price": 0.38, "best_bid": 0.61, "best_ask": 0.63,
  "spread": 0.02, "bid_depth": 1200, "ask_depth": 900, "data_health": 0.95,
  "enable_order_book": true
}]}
```
`GET /api/markets/{id}` → `{"market": {<all market columns>}, "outcomes": [{outcome_index, outcome_name, token_id, last_price, is_winner}]}`

`GET /api/markets/{id}/replay` →
```json
{"market": {...}, "resolution": {"resolved_outcome": "Up", "status": "resolved"},
 "series": {
   "price": [{"t": "..Z", "up": 0.6, "down": 0.4}],
   "book":  [{"t": "..Z", "bid": 0.59, "ask": 0.61, "mid": 0.60, "spread": 0.02}],
   "binance":   [{"t": "..Z", "p": 64000.1}],
   "chainlink": [{"t": "..Z", "p": 64001.0}]
 },
 "wallet_trades": [{"t": "..Z", "wallet": "0x..", "side": "BUY", "outcome": "Down",
                    "price": 0.97, "size": 30}]}
```

## Wallets
`GET /api/wallets` → `{"wallets": [{"address","label","is_target","last_synced_at","n_trades"}]}`

`GET /api/wallets/{address}/summary` →
```json
{"address": "0x..", "profile": {"name": "SampleBot", "pseudonym": "Sample-Bot"},
 "accounting": {
   "reported_realized_pnl": 1234.5,     "reported_source": "data-api positions",
   "reconstructed_pnl": 1180.2,         "estimated_pnl_after_fees": 1050.0,
   "portfolio_value": 0.0,              "total_volume": 50000.0, "rewards": null
 },
 "stats": {"n_trades": 900, "win_rate": 0.86, "profit_factor": 1.4,
           "avg_win": 2.1, "avg_loss": -8.0, "max_drawdown": -300.0},
 "warnings": ["..."], "skeptic_notes": ["The $21–24k claim is unverified; ..."]}
```
`GET /api/wallets/{address}/trades?limit=&offset=` → `{"total": N, "trades": [<trade rows + enrichment>]}`

`GET /api/wallets/{address}/pnl` →
`{"by_day": [{"day","reconstructed_pnl","reported_pnl","volume","n"}], "cumulative": [{"t","pnl"}]}`

`GET /api/wallets/{address}/breakdowns` →
```json
{"by_asset": [{"key","n","pnl","win_rate","volume"}],
 "by_hour": [...], "by_weekday_weekend": [...], "by_window": [...],
 "by_entry_bucket": [...], "by_time_to_expiry": [...], "by_market_age": [...],
 "entry_price_distribution": [{"bucket","n"}],
 "breakeven_by_bucket": [{"bucket","avg_entry","breakeven_winrate","actual_win_rate","edge"}]}
```

## Data quality
`GET /api/data-quality` →
```json
{"totals": {"raw": 0, "clean": 0, "duplicates": 0, "stale": 0, "out_of_order": 0,
            "reconnects": 0, "rejected": 0, "gaps": 0},
 "feeds": [{"source","token_id","asset_symbol","connected","last_message_age_s",
            "messages","duplicates","stale","out_of_order","reconnects","rejected"}],
 "market_gaps": [{"market_id","slug","expected","received","gap_count","max_gap_s"}],
 "api_errors": [{"ts","client","path","status_code","error"}]}
```

## Strategy lab
`POST /api/strategies/run` body:
```json
{"strategy": "random", "assets": ["BTC","ETH"], "windows": [5,15],
 "date_from": null, "date_to": null, "latency_ms": 100,
 "fill_model": "realistic", "fee_scenario": "conservative",
 "size": 100, "params": {}}
```
→ `{"run_id": 12, "metrics": {<StrategyRunMetric>}, "vs_random": {...}, "warnings": [...]}`

`GET /api/strategies/list` → `{"strategies": [{"key","name","description","params_schema"}]}`
`GET /api/strategies/runs` → `{"runs": [{id, strategy_key, created_at, net_pnl, win_rate, n_filled, sample_warning}]}`
`GET /api/strategies/runs/{id}` → `{"run": {...}, "metrics": {...}, "trades": [...], "vs_random": {...}}`

## Forward paper trading (LIVE, simulation only — no real orders)
`GET /api/paper/strategies` → `{"strategies": [{"key","name","needs":[..],"params":{}}]}`

`GET /api/paper/sessions` → `{"sessions": [{id, strategy_key, status, started_at, stopped_at,
  assets, windows, latency_grid_ms:[..], size, is_running, best_latency_ms, best_realized_pnl}]}`

`GET /api/paper/sessions/{id}` →
```json
{"session": {"id","strategy_key","status","started_at","stopped_at","assets","windows","size",
             "latency_grid_ms":[0,40,100,250,500,1000],"fee_scenario","is_running","config":{}},
 "by_latency": [{"latency_ms","n_decisions","n_filled","n_missed","n_settled","n_won",
                 "win_rate","realized_pnl","fees_paid","avg_slippage_vs_decision","fill_rate"}],
 "pnl_decay_vs_zero_latency": {"40": -1.2, "100": -3.0, "1000": -8.5},
 "equity_by_latency": {"0": [{"t","realized_pnl","n_settled"}], "100": [...]},
 "warnings": ["Low sample: ..."]}
```
`GET /api/paper/sessions/{id}/orders` → `{"orders": [{decision_id, latency_ms, asset,
  window_minutes, outcome, decision_ts, decision_price, fill_price, slippage_vs_decision,
  status, resolved_outcome, won, pnl, fees}]}`

`POST /api/paper/start` body `{strategy, assets?, windows?, latencies_ms?, size?, duration_s?,
  fee_scenario?, lookback_s?, params?}` → `{session_id, status:"running", note}` (duration capped 7200s)

`POST /api/paper/sessions/{id}/stop` → `{session_id, status:"stopping"}`

## Export (CSV downloads, `text/csv`)
- `GET /api/export/wallet-trades?wallet=0x..`
- `GET /api/export/market-replay?market=<id>`
- `GET /api/export/strategy-run?run_id=<id>`
