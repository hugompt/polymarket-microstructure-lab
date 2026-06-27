// Types mirror docs/API_CONTRACT.md exactly. All times are ISO-8601 UTC strings
// unless suffixed `_epoch`. Money/PnL in USDC. Prices are 0..1 probabilities.
// The DB may be empty; every shape has a valid empty form.

// ---------- Health ----------
export interface Feed {
  source: string;
  token_id: string | null;
  asset_symbol: string | null;
  connected: boolean;
  last_message_age_s: number | null;
  messages: number;
  duplicates: number;
  stale: number;
  out_of_order: number;
  reconnects: number;
  rejected: number;
}

export interface HealthCounts {
  markets: number;
  live_markets: number;
  upcoming_markets: number;
  trades: number;
  orderbook_snapshots_today: number;
  ticks_today: number;
  api_errors_today: number;
}

export interface Health {
  status: string;
  time_utc: string | null;
  db_ok: boolean;
  request_budget_remaining: number | null;
  counts: HealthCounts;
  feeds: Feed[];
  last_discovery_at: string | null;
  last_wallet_sync_at: string | null;
  warnings: string[];
}

// ---------- Markets ----------
export interface Market {
  id: number;
  slug: string;
  asset: string;
  window_minutes: number;
  title: string;
  status: string;
  start_time: string | null;
  end_time: string | null;
  seconds_to_close: number | null;
  up_price: number | null;
  down_price: number | null;
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  bid_depth: number | null;
  ask_depth: number | null;
  data_health: number | null;
  enable_order_book: boolean;
  // Allow extra columns from GET /api/markets/{id} ("all market columns").
  [key: string]: unknown;
}

export interface MarketsResponse {
  markets: Market[];
}

export interface Outcome {
  outcome_index: number;
  outcome_name: string;
  token_id: string;
  last_price: number | null;
  is_winner: boolean | null;
}

export interface MarketDetail {
  market: Market | null;
  outcomes: Outcome[];
}

// ---------- Replay ----------
export interface PricePoint {
  t: string;
  up: number | null;
  down: number | null;
}
export interface BookPoint {
  t: string;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  spread: number | null;
}
export interface PxPoint {
  t: string;
  p: number | null;
}
export interface WalletTradeMarker {
  t: string;
  wallet: string;
  side: string;
  outcome: string;
  price: number | null;
  size: number | null;
}
export interface Resolution {
  resolved_outcome: string | null;
  status: string | null;
}
export interface MarketReplay {
  market: Market | null;
  resolution: Resolution | null;
  series: {
    price: PricePoint[];
    book: BookPoint[];
    binance: PxPoint[];
    chainlink: PxPoint[];
  };
  wallet_trades: WalletTradeMarker[];
}

// ---------- Wallets ----------
export interface WalletListItem {
  address: string;
  label: string | null;
  is_target: boolean;
  last_synced_at: string | null;
  n_trades: number;
}
export interface WalletsResponse {
  wallets: WalletListItem[];
}

export interface WalletProfile {
  name: string | null;
  pseudonym: string | null;
  bio: string | null;
}
export interface WalletAccounting {
  reported_realized_pnl: number | null;
  reported_source: string | null;
  reconstructed_pnl: number | null;
  estimated_pnl_after_fees: number | null;
  estimated_fees: number | null;
  portfolio_value: number | null;
  total_volume: number | null;
  rewards: number | null;
}
export interface WalletStats {
  n_trades: number;
  n_resolved_buy_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  max_drawdown: number | null;
  sharpe_like: number | null;
  avg_entry_price: number | null;
  is_low_sample: boolean | null;
}
export interface WalletCoverage {
  n_trades: number | null;
  n_resolved_buy_trades: number | null;
  n_resolved_markets: number | null;
  resolution_coverage_pct: number | null;
}
export interface WalletSummary {
  address: string;
  profile: WalletProfile;
  accounting: WalletAccounting;
  stats: WalletStats;
  coverage: WalletCoverage;
  warnings: string[];
  skeptic_notes: string[];
}

export interface WalletTrade {
  // Trade rows + enrichment — shape is backend-defined; keep open.
  [key: string]: unknown;
}
export interface WalletTradesResponse {
  total: number;
  trades: WalletTrade[];
}

export interface PnlDay {
  day: string;
  reconstructed_pnl: number | null;
  cumulative_pnl: number | null;
  volume: number | null;
  n: number | null;
  win_rate: number | null;
}
export interface CumulativePnlPoint {
  t: string;
  pnl: number | null;
}
export interface WalletPnl {
  by_day: PnlDay[];
  cumulative: CumulativePnlPoint[];
}

export interface BreakdownRow {
  key: string | number;
  n: number | null;
  pnl: number | null;
  win_rate: number | null;
  volume: number | null;
  is_low_sample?: boolean | null;
}
export interface EntryDistRow {
  bucket: string;
  n: number;
}
export interface BreakevenRow {
  bucket: string;
  avg_entry: number | null;
  breakeven_winrate: number | null;
  actual_win_rate: number | null;
  edge: number | null;
}
export interface WalletBreakdowns {
  by_asset: BreakdownRow[];
  by_hour: BreakdownRow[];
  by_weekday_weekend: BreakdownRow[];
  by_window: BreakdownRow[];
  by_entry_bucket: BreakdownRow[];
  by_time_to_expiry: BreakdownRow[];
  by_market_age: BreakdownRow[];
  entry_price_distribution: EntryDistRow[];
  breakeven_by_bucket: BreakevenRow[];
}

// ---------- Data quality ----------
export interface DataQualityTotals {
  raw: number;
  clean: number;
  duplicates: number;
  stale: number;
  out_of_order: number;
  reconnects: number;
  rejected: number;
  gaps: number;
}
export interface DataQualityFeed {
  source: string;
  token_id: string | null;
  asset_symbol: string | null;
  connected: boolean;
  last_message_age_s: number | null;
  messages: number;
  duplicates: number;
  stale: number;
  out_of_order: number;
  reconnects: number;
  rejected: number;
}
export interface MarketGap {
  market_id: number;
  slug: string;
  expected: number;
  received: number;
  gap_count: number;
  max_gap_s: number | null;
}
export interface ApiError {
  ts: string;
  client: string;
  path: string;
  status_code: number | null;
  error: string | null;
}
export interface DataQuality {
  totals: DataQualityTotals;
  feeds: DataQualityFeed[];
  market_gaps: MarketGap[];
  api_errors: ApiError[];
}

// ---------- Strategy lab ----------
export interface StrategyParamsSchema {
  [key: string]: unknown;
}
export interface StrategyDef {
  key: string;
  name: string;
  description: string | null;
  requires: string[];
  params_schema: StrategyParamsSchema | null;
}
export interface StrategiesResponse {
  strategies: StrategyDef[];
}

export interface StrategyRunMetric {
  [key: string]: unknown;
}

// Strategy backtest breakdown row. Unlike wallet BreakdownRow, `key` may also
// be boolean (the by_weekend group keys on true/false).
export interface StrategyBreakdownRow {
  key: string | number | boolean;
  n: number | null;
  pnl: number | null;
  win_rate: number | null;
  volume: number | null;
  is_low_sample?: boolean | null;
}
// Strategy metrics.breakdowns: exactly these 5 groups (note by_weekend, not
// by_weekday_weekend, and no by_time_to_expiry/by_market_age like wallets).
export interface StrategyBreakdowns {
  by_asset: StrategyBreakdownRow[];
  by_hour: StrategyBreakdownRow[];
  by_weekend: StrategyBreakdownRow[];
  by_window: StrategyBreakdownRow[];
  by_entry_bucket: StrategyBreakdownRow[];
}

export interface StrategyRunSummary {
  id: number;
  strategy_key: string;
  label: string | null;
  created_at: string | null;
  fill_model: string | null;
  fee_scenario: string | null;
  latency_ms: number | null;
  net_pnl: number | null;
  win_rate: number | null;
  n_filled: number | null;
  vs_random_net_pnl: number | null;
  sample_warning: boolean;
}
export interface StrategyRunsResponse {
  runs: StrategyRunSummary[];
}

export interface StrategyRunRequest {
  strategy: string;
  assets: string[];
  windows: number[];
  date_from: string | null;
  date_to: string | null;
  latency_ms: number;
  fill_model: string;
  fee_scenario: string;
  size: number;
  params: Record<string, unknown>;
}
export interface StrategyRunResult {
  run_id: number | null;
  metrics: StrategyRunMetric;
  vs_random: StrategyRunMetric;
  warnings: string[];
}
export interface StrategyRunDetail {
  run: Record<string, unknown> | null;
  metrics: StrategyRunMetric;
  trades: Record<string, unknown>[];
  vs_random: StrategyRunMetric;
}

// ---------- Forward paper trading (live simulation) ----------
// Distinct from the historical Strategy Lab above: this runs a strategy
// against LIVE markets in real time and fills each decision across several
// "latency accounts" to measure how many ms cost how much money. SIM ONLY.

export interface PaperStrategyDef {
  key: string;
  name: string;
  needs: string[];
  params: Record<string, unknown>;
}
export interface PaperStrategiesResponse {
  strategies: PaperStrategyDef[];
}

export interface PaperSessionSummary {
  id: number;
  strategy_key: string;
  status: string;
  started_at: string | null;
  stopped_at: string | null;
  assets: string[];
  windows: number[];
  latency_grid_ms: number[];
  size: number | null;
  is_running: boolean;
  best_latency_ms: number | null;
  best_realized_pnl: number | null;
}
export interface PaperSessionsResponse {
  sessions: PaperSessionSummary[];
}

export interface PaperSession {
  id: number;
  strategy_key: string;
  status: string;
  started_at: string | null;
  stopped_at: string | null;
  assets: string[];
  windows: number[];
  size: number | null;
  latency_grid_ms: number[];
  fee_scenario: string | null;
  is_running: boolean;
  config: Record<string, unknown>;
}

// One row per latency account. The centerpiece comparison.
export interface PaperLatencyRow {
  latency_ms: number;
  n_decisions: number;
  n_filled: number;
  n_missed: number;
  n_settled: number;
  n_won: number;
  win_rate: number | null;
  realized_pnl: number;
  fees_paid: number;
  avg_slippage_vs_decision: number;
  fill_rate: number | null;
}

export interface PaperEquityPoint {
  t: string;
  realized_pnl: number;
  n_settled: number;
}

export interface PaperSessionDetail {
  session: PaperSession | null;
  by_latency: PaperLatencyRow[];
  // PnL delta vs the 0ms account, keyed by latency string.
  pnl_decay_vs_zero_latency: Record<string, number>;
  // One equity series per latency, keyed by latency string.
  equity_by_latency: Record<string, PaperEquityPoint[]>;
  warnings: string[];
}

export interface PaperOrder {
  decision_id: number | string;
  latency_ms: number;
  asset: string;
  window_minutes: number;
  outcome: string;
  decision_ts: string | null;
  decision_price: number | null;
  fill_price: number | null;
  slippage_vs_decision: number | null;
  status: string;
  resolved_outcome: string | null;
  won: boolean | null;
  pnl: number | null;
  fees: number | null;
}
export interface PaperOrdersResponse {
  orders: PaperOrder[];
}

export interface PaperStartRequest {
  strategy: string;
  assets?: string[];
  windows?: number[];
  latencies_ms?: number[];
  size?: number;
  duration_s?: number;
  fee_scenario?: string;
  lookback_s?: number;
  params?: Record<string, unknown>;
}
export interface PaperStartResult {
  session_id: number | null;
  status: string;
  note: string;
}
export interface PaperStopResult {
  session_id: number | null;
  status: string;
}
