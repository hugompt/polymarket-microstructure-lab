"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useMemo } from "react";
import {
  emptyReplay,
  exportMarketReplayUrl,
  getMarketReplay,
} from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { StatusPill } from "@/components/StatusPill";
import { ExportButton } from "@/components/ExportButton";
import { AsyncBoundary, EmptyState } from "@/components/States";
import {
  TimeSeriesChart,
  type TradeMarker,
} from "@/components/charts/TimeSeriesChart";
import { CHART } from "@/components/charts/chartTheme";
import { price, num, utc, usd } from "@/lib/format";
import type { MarketReplay } from "@/lib/types";

const toEpoch = (t: string | null): number => {
  if (!t) return NaN;
  const ms = new Date(t).getTime();
  return Number.isNaN(ms) ? NaN : ms;
};

export default function ReplayPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";

  const { data, loading, loaded, error, refetch } = useApi<MarketReplay>(
    () => getMarketReplay(id),
    emptyReplay(),
    [id]
  );

  const { priceData, bookData, binanceData, chainlinkData, markers } = useMemo(
    () => buildSeries(data),
    [data]
  );

  const m = data.market;
  const res = data.resolution;
  const hasAny =
    priceData.length +
      bookData.length +
      binanceData.length +
      chainlinkData.length >
    0;

  return (
    <div>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Link href="/live" className="text-muted hover:text-accent">
              Live
            </Link>
            <span className="text-muted">/</span>
            <span>Replay #{id}</span>
          </span>
        }
        subtitle={
          m
            ? `${String(m.title ?? m.slug ?? "")}`
            : "Historical reconstruction of a single market: price, book, oracle feeds, and target-wallet trades."
        }
        actions={<ExportButton href={exportMarketReplayUrl(id)} />}
      />

      <AsyncBoundary
        loading={loading}
        loaded={loaded}
        error={error}
        isEmpty={!m && !hasAny}
        onRetry={refetch}
        emptyTitle="No replay data"
        emptyBody="This market has no recorded series yet, or the id is unknown. Collectors must have captured it while live."
      >
        <div className="space-y-5">
          {/* Market summary + resolution */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Asset" value={String(m?.asset ?? "—")} />
            <StatCard
              label="Window"
              value={m?.window_minutes ? `${m.window_minutes}m` : "—"}
            />
            <StatCard
              label="Resolution"
              value={
                res?.resolved_outcome ? (
                  <span
                    className={
                      res.resolved_outcome.toLowerCase() === "up"
                        ? "text-up"
                        : "text-down"
                    }
                  >
                    {res.resolved_outcome}
                  </span>
                ) : (
                  "unresolved"
                )
              }
              hint={res?.status ? `status: ${res.status}` : undefined}
            />
            <StatCard
              label="Wallet trades shown"
              value={markers.length}
              hint="target wallet, overlaid on price"
            />
          </div>

          {/* Price chart with wallet-trade markers */}
          <SectionCard
            title="Up / Down price"
            subtitle="Outcome probabilities (0–1) over time. Dots = target-wallet trades (green BUY, red SELL). Times in UTC."
          >
            {priceData.length === 0 ? (
              <EmptyState title="No price series" body="No price ticks recorded for this market." />
            ) : (
              <TimeSeriesChart
                data={priceData}
                yDomain={[0, 1]}
                yTickFormatter={(v) => v.toFixed(2)}
                lines={[
                  { dataKey: "up", name: "Up", color: CHART.up },
                  { dataKey: "down", name: "Down", color: CHART.down },
                ]}
                markers={markers}
              />
            )}
          </SectionCard>

          {/* Best bid/ask + spread */}
          <SectionCard
            title="Best bid / ask & spread"
            subtitle="Top-of-book over time. Spread plotted on the right axis."
          >
            {bookData.length === 0 ? (
              <EmptyState title="No book series" body="No order-book snapshots recorded." />
            ) : (
              <TimeSeriesChart
                data={bookData}
                yDomain={[0, 1]}
                yTickFormatter={(v) => v.toFixed(2)}
                lines={[
                  { dataKey: "bid", name: "Best bid", color: CHART.accent },
                  { dataKey: "ask", name: "Best ask", color: CHART.amber },
                  { dataKey: "mid", name: "Mid", color: CHART.muted },
                ]}
                rightLines={[
                  { dataKey: "spread", name: "Spread", color: CHART.violet },
                ]}
                rightYTickFormatter={(v) => v.toFixed(3)}
              />
            )}
          </SectionCard>

          {/* Oracle feeds */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <SectionCard
              title="Binance price"
              subtitle="Reference spot price (USD)."
            >
              {binanceData.length === 0 ? (
                <EmptyState title="No Binance series" body="No Binance ticks recorded." />
              ) : (
                <TimeSeriesChart
                  data={binanceData}
                  lines={[{ dataKey: "p", name: "Binance", color: CHART.cyan }]}
                  yTickFormatter={(v) => usd(v, 0)}
                />
              )}
            </SectionCard>
            <SectionCard
              title="Chainlink price"
              subtitle="Oracle price used for resolution (USD)."
            >
              {chainlinkData.length === 0 ? (
                <EmptyState title="No Chainlink series" body="No Chainlink ticks recorded." />
              ) : (
                <TimeSeriesChart
                  data={chainlinkData}
                  lines={[
                    { dataKey: "p", name: "Chainlink", color: CHART.violet },
                  ]}
                  yTickFormatter={(v) => usd(v, 0)}
                />
              )}
            </SectionCard>
          </div>

          {/* Wallet trades table for this market */}
          <SectionCard
            title="Target-wallet trades in this market"
            subtitle="The dots above, listed. Prices are 0–1 probabilities."
          >
            {data.wallet_trades.length === 0 ? (
              <EmptyState
                title="No wallet trades"
                body="The target wallet did not trade this market (or trades aren't recorded yet)."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-3 py-2 text-left">Time (UTC)</th>
                      <th className="px-3 py-2 text-left">Side</th>
                      <th className="px-3 py-2 text-left">Outcome</th>
                      <th className="px-3 py-2 text-right">Price</th>
                      <th className="px-3 py-2 text-right">Size</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.wallet_trades.map((t, i) => (
                      <tr
                        key={i}
                        className="border-b border-border/60 last:border-0"
                      >
                        <td className="px-3 py-1.5">{utc(t.t)}</td>
                        <td className="px-3 py-1.5">
                          <StatusPill
                            tone={
                              t.side?.toUpperCase() === "BUY" ? "good" : "bad"
                            }
                          >
                            {t.side}
                          </StatusPill>
                        </td>
                        <td className="px-3 py-1.5">{t.outcome}</td>
                        <td className="tnum px-3 py-1.5 text-right">
                          {price(t.price)}
                        </td>
                        <td className="tnum px-3 py-1.5 text-right">
                          {num(t.size, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </div>
      </AsyncBoundary>
    </div>
  );
}

function buildSeries(data: MarketReplay) {
  const priceData = data.series.price
    .map((p) => ({ xEpoch: toEpoch(p.t), up: p.up, down: p.down }))
    .filter((p) => !Number.isNaN(p.xEpoch));

  const bookData = data.series.book
    .map((b) => ({
      xEpoch: toEpoch(b.t),
      bid: b.bid,
      ask: b.ask,
      mid: b.mid,
      spread: b.spread,
    }))
    .filter((b) => !Number.isNaN(b.xEpoch));

  const binanceData = data.series.binance
    .map((b) => ({ xEpoch: toEpoch(b.t), p: b.p }))
    .filter((b) => !Number.isNaN(b.xEpoch));

  const chainlinkData = data.series.chainlink
    .map((b) => ({ xEpoch: toEpoch(b.t), p: b.p }))
    .filter((b) => !Number.isNaN(b.xEpoch));

  const markers: TradeMarker[] = data.wallet_trades
    .map((t) => ({
      x: toEpoch(t.t),
      // Plot a trade at the probability it transacted at.
      y: typeof t.price === "number" ? t.price : NaN,
      side: t.side,
      outcome: t.outcome,
      size: t.size,
    }))
    .filter((mk) => !Number.isNaN(mk.x) && !Number.isNaN(mk.y));

  return { priceData, bookData, binanceData, chainlinkData, markers };
}
