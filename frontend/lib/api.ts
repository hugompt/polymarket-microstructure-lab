// Typed fetch client for the polymarket-microstructure-lab backend.
//
// Contract: docs/API_CONTRACT.md. Base URL from NEXT_PUBLIC_API_BASE
// (default http://localhost:8000). Every call catches network/parse errors and
// returns a typed empty/fallback value so pages NEVER crash when the backend is
// down or the DB is empty. Callers can inspect the `ok` flag via fetchJson if
// they need to distinguish "down" from "empty"; the high-level getters always
// resolve.

import type {
  ApiError,
  DataQuality,
  Health,
  MarketDetail,
  MarketReplay,
  MarketsResponse,
  PaperOrdersResponse,
  PaperSessionDetail,
  PaperSessionsResponse,
  PaperStartRequest,
  PaperStartResult,
  PaperStopResult,
  PaperStrategiesResponse,
  StrategiesResponse,
  StrategyRunDetail,
  StrategyRunRequest,
  StrategyRunResult,
  StrategyRunsResponse,
  WalletBreakdowns,
  WalletPnl,
  WalletsResponse,
  WalletSummary,
  WalletTradesResponse,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
  "http://localhost:8000";

// Optional: pre-fill the wallet view with a target. Set NEXT_PUBLIC_TARGET_WALLET (a PUBLIC
// on-chain address) and NEXT_PUBLIC_TARGET_PROFILE at build time. Empty by default — the user
// just types any wallet address into the dashboard.
export const TARGET_WALLET =
  process.env.NEXT_PUBLIC_TARGET_WALLET?.trim() || "";
export const TARGET_WALLET_PROFILE =
  process.env.NEXT_PUBLIC_TARGET_PROFILE?.trim() || "";

export interface FetchResult<T> {
  ok: boolean;
  data: T;
  /** Human-readable error if the request failed; null on success. */
  error: string | null;
}

/**
 * Core fetcher. Returns { ok, data, error }; on any failure `data` is the
 * provided `fallback`. Never throws.
 */
export async function fetchJson<T>(
  path: string,
  fallback: T,
  init?: RequestInit
): Promise<FetchResult<T>> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  try {
    const res = await fetch(url, {
      // Always hit the live backend; this is a real-time research tool.
      cache: "no-store",
      headers: { Accept: "application/json", ...(init?.headers || {}) },
      ...init,
    });
    if (!res.ok) {
      return {
        ok: false,
        data: fallback,
        error: `HTTP ${res.status} ${res.statusText} for ${path}`,
      };
    }
    const json = (await res.json()) as T;
    return { ok: true, data: json, error: null };
  } catch (err) {
    const msg =
      err instanceof Error ? err.message : "Network error (backend unreachable)";
    return { ok: false, data: fallback, error: msg };
  }
}

// ---------- Fallback factories ----------

export function emptyHealth(): Health {
  return {
    status: "unknown",
    time_utc: null,
    db_ok: false,
    request_budget_remaining: null,
    counts: {
      markets: 0,
      live_markets: 0,
      upcoming_markets: 0,
      trades: 0,
      orderbook_snapshots_today: 0,
      ticks_today: 0,
      api_errors_today: 0,
    },
    feeds: [],
    last_discovery_at: null,
    last_wallet_sync_at: null,
    warnings: [],
  };
}

const emptyMarkets = (): MarketsResponse => ({ markets: [] });
const emptyMarketDetail = (): MarketDetail => ({ market: null, outcomes: [] });
export const emptyReplay = (): MarketReplay => ({
  market: null,
  resolution: null,
  series: { price: [], book: [], binance: [], chainlink: [] },
  wallet_trades: [],
});
const emptyWallets = (): WalletsResponse => ({ wallets: [] });
const emptyWalletSummary = (address: string): WalletSummary => ({
  address,
  profile: { name: null, pseudonym: null, bio: null },
  accounting: {
    reported_realized_pnl: null,
    reported_source: null,
    reconstructed_pnl: null,
    estimated_pnl_after_fees: null,
    estimated_fees: null,
    portfolio_value: null,
    total_volume: null,
    rewards: null,
  },
  stats: {
    n_trades: 0,
    n_resolved_buy_trades: null,
    win_rate: null,
    profit_factor: null,
    avg_win: null,
    avg_loss: null,
    max_drawdown: null,
    sharpe_like: null,
    avg_entry_price: null,
    is_low_sample: null,
  },
  coverage: {
    n_trades: null,
    n_resolved_buy_trades: null,
    n_resolved_markets: null,
    resolution_coverage_pct: null,
  },
  warnings: [],
  skeptic_notes: [],
});
const emptyTrades = (): WalletTradesResponse => ({ total: 0, trades: [] });
const emptyPnl = (): WalletPnl => ({ by_day: [], cumulative: [] });
const emptyBreakdowns = (): WalletBreakdowns => ({
  by_asset: [],
  by_hour: [],
  by_weekday_weekend: [],
  by_window: [],
  by_entry_bucket: [],
  by_time_to_expiry: [],
  by_market_age: [],
  entry_price_distribution: [],
  breakeven_by_bucket: [],
});
const emptyDataQuality = (): DataQuality => ({
  totals: {
    raw: 0,
    clean: 0,
    duplicates: 0,
    stale: 0,
    out_of_order: 0,
    reconnects: 0,
    rejected: 0,
    gaps: 0,
  },
  feeds: [],
  market_gaps: [],
  api_errors: [] as ApiError[],
});
const emptyStrategies = (): StrategiesResponse => ({ strategies: [] });
const emptyRuns = (): StrategyRunsResponse => ({ runs: [] });
const emptyRunResult = (): StrategyRunResult => ({
  run_id: null,
  metrics: {},
  vs_random: {},
  warnings: [],
});
const emptyRunDetail = (): StrategyRunDetail => ({
  run: null,
  metrics: {},
  trades: [],
  vs_random: {},
});

// ---------- Paper-trading fallbacks ----------
const emptyPaperStrategies = (): PaperStrategiesResponse => ({ strategies: [] });
const emptyPaperSessions = (): PaperSessionsResponse => ({ sessions: [] });
const emptyPaperDetail = (): PaperSessionDetail => ({
  session: null,
  by_latency: [],
  pnl_decay_vs_zero_latency: {},
  equity_by_latency: {},
  warnings: [],
});
const emptyPaperOrders = (): PaperOrdersResponse => ({ orders: [] });
const emptyPaperStart = (): PaperStartResult => ({
  session_id: null,
  status: "error",
  note: "",
});
const emptyPaperStop = (): PaperStopResult => ({
  session_id: null,
  status: "error",
});

// ---------- Endpoint functions ----------

export const getHealth = () => fetchJson<Health>("/api/health", emptyHealth());

export const getLiveMarkets = () =>
  fetchJson<MarketsResponse>("/api/markets/live", emptyMarkets());

export const getUpcomingMarkets = () =>
  fetchJson<MarketsResponse>("/api/markets/upcoming", emptyMarkets());

export const getMarket = (id: string | number) =>
  fetchJson<MarketDetail>(`/api/markets/${id}`, emptyMarketDetail());

export const getMarketReplay = (id: string | number) =>
  fetchJson<MarketReplay>(`/api/markets/${id}/replay`, emptyReplay());

export const getWallets = () =>
  fetchJson<WalletsResponse>("/api/wallets", emptyWallets());

export const getWalletSummary = (address: string) =>
  fetchJson<WalletSummary>(
    `/api/wallets/${address}/summary`,
    emptyWalletSummary(address)
  );

export const getWalletTrades = (address: string, limit = 50, offset = 0) =>
  fetchJson<WalletTradesResponse>(
    `/api/wallets/${address}/trades?limit=${limit}&offset=${offset}`,
    emptyTrades()
  );

export const getWalletPnl = (address: string) =>
  fetchJson<WalletPnl>(`/api/wallets/${address}/pnl`, emptyPnl());

export const getWalletBreakdowns = (address: string) =>
  fetchJson<WalletBreakdowns>(
    `/api/wallets/${address}/breakdowns`,
    emptyBreakdowns()
  );

export const getDataQuality = () =>
  fetchJson<DataQuality>("/api/data-quality", emptyDataQuality());

export const listStrategies = () =>
  fetchJson<StrategiesResponse>("/api/strategies/list", emptyStrategies());

export const runStrategy = (body: StrategyRunRequest) =>
  fetchJson<StrategyRunResult>("/api/strategies/run", emptyRunResult(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const listStrategyRuns = () =>
  fetchJson<StrategyRunsResponse>("/api/strategies/runs", emptyRuns());

export const getStrategyRun = (id: string | number) =>
  fetchJson<StrategyRunDetail>(`/api/strategies/runs/${id}`, emptyRunDetail());

// ---------- Forward paper trading (live simulation) ----------

export const listPaperStrategies = () =>
  fetchJson<PaperStrategiesResponse>(
    "/api/paper/strategies",
    emptyPaperStrategies()
  );

export const listPaperSessions = () =>
  fetchJson<PaperSessionsResponse>("/api/paper/sessions", emptyPaperSessions());

export const getPaperSession = (id: string | number) =>
  fetchJson<PaperSessionDetail>(
    `/api/paper/sessions/${id}`,
    emptyPaperDetail()
  );

export const getPaperOrders = (id: string | number, limit = 200) =>
  fetchJson<PaperOrdersResponse>(
    `/api/paper/sessions/${id}/orders?limit=${limit}`,
    emptyPaperOrders()
  );

export const startPaper = (body: PaperStartRequest) =>
  fetchJson<PaperStartResult>("/api/paper/start", emptyPaperStart(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const stopPaper = (id: string | number) =>
  fetchJson<PaperStopResult>(
    `/api/paper/sessions/${id}/stop`,
    emptyPaperStop(),
    { method: "POST" }
  );

// ---------- Export (CSV) URL builders ----------
// These are GET endpoints returning text/csv; link to them directly so the
// browser downloads. We just construct absolute URLs.

export const exportWalletTradesUrl = (wallet: string) =>
  `${API_BASE}/api/export/wallet-trades?wallet=${encodeURIComponent(wallet)}`;

export const exportMarketReplayUrl = (market: string | number) =>
  `${API_BASE}/api/export/market-replay?market=${encodeURIComponent(
    String(market)
  )}`;

export const exportStrategyRunUrl = (runId: string | number) =>
  `${API_BASE}/api/export/strategy-run?run_id=${encodeURIComponent(
    String(runId)
  )}`;
