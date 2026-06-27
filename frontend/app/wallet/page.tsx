"use client";

import { useState } from "react";
import {
  TARGET_WALLET,
  TARGET_WALLET_PROFILE,
  exportWalletTradesUrl,
  getWalletBreakdowns,
  getWalletPnl,
  getWalletSummary,
  getWalletTrades,
} from "@/lib/api";
import { useApi, type ApiState } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { StatusPill } from "@/components/StatusPill";
import { WarningPanel } from "@/components/WarningPanel";
import { ExportButton } from "@/components/ExportButton";
import { AsyncBoundary, EmptyState, LoadingState } from "@/components/States";
import { BarChartCard, type BarDatum } from "@/components/charts/BarChart";
import { CumulativeChart } from "@/components/charts/CumulativeChart";
import { CHART } from "@/components/charts/chartTheme";
import {
  num,
  pct,
  shortAddr,
  signColor,
  usd,
  usdCompact,
  utc,
} from "@/lib/format";
import type {
  BreakdownRow,
  WalletBreakdowns,
  WalletPnl,
  WalletSummary,
  WalletTradesResponse,
} from "@/lib/types";

const PAGE_SIZE = 25;

export default function WalletPage() {
  // The address actually being queried (committed via the form).
  const [address, setAddress] = useState<string>(TARGET_WALLET);
  const [input, setInput] = useState<string>(TARGET_WALLET);
  const [page, setPage] = useState(0);

  const summary = useApi<WalletSummary>(
    () => getWalletSummary(address),
    {
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
    },
    [address]
  );

  const pnl = useApi<WalletPnl>(
    () => getWalletPnl(address),
    { by_day: [], cumulative: [] },
    [address]
  );

  const breakdowns = useApi<WalletBreakdowns>(
    () => getWalletBreakdowns(address),
    {
      by_asset: [],
      by_hour: [],
      by_weekday_weekend: [],
      by_window: [],
      by_entry_bucket: [],
      by_time_to_expiry: [],
      by_market_age: [],
      entry_price_distribution: [],
      breakeven_by_bucket: [],
    },
    [address]
  );

  const trades = useApi<WalletTradesResponse>(
    () => getWalletTrades(address, PAGE_SIZE, page * PAGE_SIZE),
    { total: 0, trades: [] },
    [address, page]
  );

  const s = summary.data;
  const acc = s.accounting;
  const st = s.stats;
  const isTarget =
    !!TARGET_WALLET && address.toLowerCase() === TARGET_WALLET.toLowerCase();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const next = input.trim();
    if (next && next !== address) {
      setPage(0);
      setAddress(next);
    }
  }

  return (
    <div>
      <PageHeader
        title="Wallet Analysis"
        subtitle="Three different PnL figures are shown side-by-side on purpose. They are NOT the same thing, and a balance is never presented as profit."
        actions={<ExportButton href={exportWalletTradesUrl(address)} />}
      />

      {/* Address selector */}
      <form
        onSubmit={submit}
        className="mb-5 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          spellCheck={false}
          placeholder="0x… wallet address"
          className="min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-3 py-1.5 font-mono text-sm text-foreground outline-none focus:border-accent/60"
        />
        <button
          type="submit"
          className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/20"
        >
          Analyze
        </button>
        {TARGET_WALLET && (
          <button
            type="button"
            onClick={() => {
              setInput(TARGET_WALLET);
              setPage(0);
              setAddress(TARGET_WALLET);
            }}
            className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm text-muted hover:text-foreground"
          >
            Reset to target
          </button>
        )}
      </form>

      {/* Identity row */}
      <div className="mb-5 flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono text-muted">{shortAddr(address)}</span>
        {isTarget && (
          <StatusPill tone="accent">target wallet</StatusPill>
        )}
        {s.profile.name && (
          <StatusPill tone="neutral">{s.profile.name}</StatusPill>
        )}
        {s.profile.pseudonym && (
          <span className="text-muted">“{s.profile.pseudonym}”</span>
        )}
        {isTarget && !s.profile.name && (
          <StatusPill tone="neutral">{TARGET_WALLET_PROFILE}</StatusPill>
        )}
      </div>

      {summary.loading && !summary.loaded ? (
        <SectionCard>
          <LoadingState />
        </SectionCard>
      ) : (
        <div className="space-y-5">
          {/* Skeptic notes + warnings — prominent, before any numbers */}
          <WarningPanel
            title="Skeptic notes"
            tone="info"
            icon="🔍"
            items={s.skeptic_notes}
            emptyMessage="No skeptic notes returned. Treat all PnL figures below as estimates, not audited results."
          />
          <WarningPanel
            title="Data warnings"
            tone="warn"
            items={
              summary.error
                ? [`Backend unreachable: ${summary.error}`, ...s.warnings]
                : s.warnings
            }
          />

          {/* THE THREE PnL NUMBERS — clearly separated and labelled */}
          <div>
            <h2 className="mb-2 text-sm font-semibold text-foreground">
              PnL — three different measures
            </h2>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <StatCard
                label="Reported realized PnL"
                value={usd(acc.reported_realized_pnl)}
                tone={pnlTone(acc.reported_realized_pnl)}
                hint={
                  <>
                    Self-reported by the data API
                    {acc.reported_source ? ` (${acc.reported_source})` : ""}.
                    Unverified.
                  </>
                }
              />
              <StatCard
                label="Reconstructed PnL"
                value={usd(acc.reconstructed_pnl)}
                tone={pnlTone(acc.reconstructed_pnl)}
                hint="Recomputed from observed trades by this lab. Excludes fees."
              />
              <StatCard
                label="Estimated PnL after fees"
                value={usd(acc.estimated_pnl_after_fees)}
                tone={pnlTone(acc.estimated_pnl_after_fees)}
                hint="Reconstructed PnL minus modelled fees. The most conservative figure."
              />
            </div>
          </div>

          {/* Balance / volume — explicitly NOT profit */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard
              label="Portfolio value"
              value={usd(acc.portfolio_value)}
              hint="Current account balance — NOT profit. A wallet can hold funds it never earned."
            />
            <StatCard
              label="Total volume"
              value={usdCompact(acc.total_volume)}
              hint="Gross traded notional, not a gain."
            />
            <StatCard
              label="Rewards"
              value={acc.rewards === null ? "n/a" : usd(acc.rewards)}
              hint="Maker/LP rewards if any; separate from trading PnL."
            />
          </div>

          {/* Trading stats */}
          <SectionCard title="Trading stats" subtitle="Win rate ≠ profitability — see break-even analysis below.">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Trades" value={num(st.n_trades, 0)} />
              <Stat label="Win rate" value={pct(st.win_rate)} />
              <Stat label="Profit factor" value={num(st.profit_factor)} />
              <Stat label="Avg win" value={usd(st.avg_win)} tone={signColor(st.avg_win)} />
              <Stat label="Avg loss" value={usd(st.avg_loss)} tone={signColor(st.avg_loss)} />
              <Stat label="Max drawdown" value={usd(st.max_drawdown)} tone={signColor(st.max_drawdown)} />
            </div>
          </SectionCard>

          {/* Cumulative PnL */}
          <SectionCard
            title="Cumulative reconstructed PnL"
            subtitle="Equity curve over time (UTC). Excludes fees."
          >
            <AsyncBoundary
              loading={pnl.loading}
              loaded={pnl.loaded}
              error={pnl.error}
              isEmpty={pnl.data.cumulative.length === 0}
              onRetry={pnl.refetch}
              emptyTitle="No PnL history"
              emptyBody="No daily PnL reconstructed yet."
            >
              <CumulativeChart
                data={pnl.data.cumulative
                  .map((p) => ({
                    xEpoch: new Date(p.t).getTime(),
                    pnl: p.pnl ?? 0,
                  }))
                  .filter((p) => !Number.isNaN(p.xEpoch))}
              />
            </AsyncBoundary>
          </SectionCard>

          {/* Breakdown charts */}
          <BreakdownCharts b={breakdowns} />

          {/* Break-even vs actual win rate */}
          <BreakevenTable rows={breakdowns.data.breakeven_by_bucket} />

          {/* Trades table */}
          <TradesTable
            trades={trades.data}
            page={page}
            loading={trades.loading}
            loaded={trades.loaded}
            error={trades.error}
            onRetry={trades.refetch}
            onPage={setPage}
          />
        </div>
      )}
    </div>
  );
}

function pnlTone(v: number | null): "good" | "bad" | "default" {
  if (v === null) return "default";
  return v >= 0 ? "good" : "bad";
}

function Stat({
  label,
  value,
  tone = "text-foreground",
}: {
  label: string;
  value: React.ReactNode;
  tone?: string;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`tnum mt-0.5 text-lg font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

// ---------- Breakdown charts ----------
function toPnlBars(rows: BreakdownRow[]): BarDatum[] {
  return rows.map((r) => ({ label: String(r.key), value: r.pnl ?? 0 }));
}

function BreakdownCharts({ b }: { b: ApiState<WalletBreakdowns> }) {
  const data = b.data;
  const dist: BarDatum[] = data.entry_price_distribution.map((d) => ({
    label: d.bucket,
    value: d.n,
  }));

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <SectionCard title="PnL by asset" subtitle="Reconstructed PnL grouped by asset.">
        {data.by_asset.length === 0 ? (
          <EmptyState title="No data" body="No per-asset breakdown yet." />
        ) : (
          <BarChartCard
            data={toPnlBars(data.by_asset)}
            signedColors
            valueFormatter={(v) => usd(v)}
            yTickFormatter={(v) => usdCompact(v)}
          />
        )}
      </SectionCard>

      <SectionCard title="PnL by hour (UTC)" subtitle="Which hours of the day the wallet makes or loses money.">
        {data.by_hour.length === 0 ? (
          <EmptyState title="No data" body="No hourly breakdown yet." />
        ) : (
          <BarChartCard
            data={toPnlBars(data.by_hour)}
            signedColors
            valueFormatter={(v) => usd(v)}
            yTickFormatter={(v) => usdCompact(v)}
          />
        )}
      </SectionCard>

      <SectionCard title="Weekday vs weekend" subtitle="Reconstructed PnL split by part of week.">
        {data.by_weekday_weekend.length === 0 ? (
          <EmptyState title="No data" body="No weekday/weekend breakdown yet." />
        ) : (
          <BarChartCard
            data={toPnlBars(data.by_weekday_weekend)}
            signedColors
            valueFormatter={(v) => usd(v)}
            yTickFormatter={(v) => usdCompact(v)}
          />
        )}
      </SectionCard>

      <SectionCard title="Entry price distribution" subtitle="How many trades fall in each entry-probability bucket.">
        {dist.length === 0 || dist.every((d) => d.value === 0) ? (
          <EmptyState title="No data" body="No entry-price distribution yet." />
        ) : (
          <BarChartCard
            data={dist}
            color={CHART.accent}
            valueFormatter={(v) => `${v} trades`}
            angledLabels={dist.length > 8}
          />
        )}
      </SectionCard>
    </div>
  );
}

// ---------- Break-even table ----------
function BreakevenTable({
  rows,
}: {
  rows: WalletBreakdowns["breakeven_by_bucket"];
}) {
  return (
    <SectionCard
      title="Break-even win rate vs actual"
      subtitle="At a given entry price p, you must win > p of the time just to break even. Buckets where actual < break-even (negative edge) are highlighted red — those trades lose money on average regardless of a high headline win rate."
    >
      {rows.length === 0 ? (
        <EmptyState title="No data" body="No break-even analysis yet." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2 text-left">Entry bucket</th>
                <th className="px-3 py-2 text-right">Avg entry</th>
                <th className="px-3 py-2 text-right">Break-even win %</th>
                <th className="px-3 py-2 text-right">Actual win %</th>
                <th className="px-3 py-2 text-right">Edge</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const negative =
                  typeof r.edge === "number"
                    ? r.edge < 0
                    : typeof r.actual_win_rate === "number" &&
                      typeof r.breakeven_winrate === "number"
                      ? r.actual_win_rate < r.breakeven_winrate
                      : false;
                return (
                  <tr
                    key={i}
                    className={`border-b border-border/60 last:border-0 ${
                      negative ? "bg-down/10" : ""
                    }`}
                  >
                    <td className="px-3 py-1.5">{r.bucket}</td>
                    <td className="tnum px-3 py-1.5 text-right">
                      {num(r.avg_entry, 3)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right">
                      {pct(r.breakeven_winrate)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right">
                      {pct(r.actual_win_rate)}
                    </td>
                    <td
                      className={`tnum px-3 py-1.5 text-right font-medium ${
                        negative ? "text-down" : "text-up"
                      }`}
                    >
                      {r.edge === null ? "—" : pct(r.edge)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

// ---------- Trades table ----------
function TradesTable({
  trades,
  page,
  loading,
  loaded,
  error,
  onRetry,
  onPage,
}: {
  trades: WalletTradesResponse;
  page: number;
  loading: boolean;
  loaded: boolean;
  error: string | null;
  onRetry: () => void;
  onPage: (p: number) => void;
}) {
  const rows = trades.trades;
  // Derive columns from the union of keys present in the rows (backend-defined).
  const keys = deriveKeys(rows);
  const totalPages = Math.max(1, Math.ceil(trades.total / PAGE_SIZE));

  return (
    <SectionCard
      title="Trades"
      subtitle={`${num(trades.total, 0)} total · page ${page + 1} of ${totalPages}`}
      actions={
        <div className="flex items-center gap-1">
          <button
            disabled={page === 0}
            onClick={() => onPage(page - 1)}
            className="rounded-md border border-border bg-surface-2 px-2.5 py-1 text-xs disabled:opacity-40"
          >
            ← Prev
          </button>
          <button
            disabled={page + 1 >= totalPages}
            onClick={() => onPage(page + 1)}
            className="rounded-md border border-border bg-surface-2 px-2.5 py-1 text-xs disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      }
    >
      <AsyncBoundary
        loading={loading}
        loaded={loaded}
        error={error}
        isEmpty={rows.length === 0}
        onRetry={onRetry}
        emptyTitle="No trades"
        emptyBody="No trades recorded for this wallet yet."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                {keys.map((k) => (
                  <th key={k} className="px-3 py-2 text-left whitespace-nowrap">
                    {k}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-border/60 last:border-0">
                  {keys.map((k) => (
                    <td
                      key={k}
                      className="tnum px-3 py-1.5 whitespace-nowrap text-foreground/90"
                    >
                      {renderCell(k, row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncBoundary>
    </SectionCard>
  );
}

// Columns we never surface: `asset` is the raw 70-digit CLOB token-id, which is
// noise — the `slug` already conveys the underlying asset.
const HIDDEN_TRADE_COLUMNS = new Set(["asset"]);

function deriveKeys(rows: Record<string, unknown>[]): string[] {
  const set = new Set<string>();
  for (const r of rows.slice(0, 20)) {
    for (const k of Object.keys(r)) {
      if (!HIDDEN_TRADE_COLUMNS.has(k)) set.add(k);
    }
  }
  return [...set];
}

function renderCell(key: string, v: unknown): React.ReactNode {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    // Heuristic: treat *price* fields as 0..1, money fields as USD.
    if (/price|prob/i.test(key)) return v.toFixed(3);
    if (/pnl|fee|usd|value|size|amount|volume/i.test(key)) return usd(v);
    if (/time|_at|date|ts/i.test(key)) return String(v);
    return num(v, 2);
  }
  if (typeof v === "string") {
    // ISO timestamps -> compact UTC.
    if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return utc(v);
    return v;
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  return JSON.stringify(v);
}
