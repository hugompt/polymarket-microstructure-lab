"use client";

import { SectionCard } from "@/components/SectionCard";
import { StatusPill } from "@/components/StatusPill";
import { BarChartCard, type BarDatum } from "@/components/charts/BarChart";
import { num, pct, usd, price, signColor } from "@/lib/format";
import type { PaperLatencyRow } from "@/lib/types";

/**
 * THE centerpiece. Renders, for a session:
 *   - a bar chart of realized PnL by latency (visually: higher latency = worse),
 *   - a decay callout (PnL lost vs the 0ms account at each tier),
 *   - the per-latency table, with the best latency row highlighted.
 */
export function LatencyComparison({
  byLatency,
  decay,
  bestLatencyMs,
}: {
  byLatency: PaperLatencyRow[];
  decay: Record<string, number>;
  bestLatencyMs: number | null;
}) {
  if (byLatency.length === 0) {
    return (
      <SectionCard title="Latency comparison">
        <p className="px-1 py-6 text-center text-sm text-muted">
          No decisions filled yet. Latency accounts populate as the strategy
          acts on live markets.
        </p>
      </SectionCard>
    );
  }

  // Sort ascending by latency so the chart reads left (fast) to right (slow).
  const rows = [...byLatency].sort((a, b) => a.latency_ms - b.latency_ms);

  const bars: BarDatum[] = rows.map((r) => ({
    label: `${r.latency_ms}ms`,
    value: r.realized_pnl,
  }));

  // Decay tiers (skip 0ms baseline; show how much each slower tier gives up).
  const decayTiers = Object.entries(decay)
    .map(([k, v]) => ({ latency: Number(k), delta: v }))
    .filter((d) => Number.isFinite(d.latency) && d.latency > 0)
    .sort((a, b) => a.latency - b.latency);

  return (
    <SectionCard
      title="Latency comparison"
      subtitle="How many milliseconds cost how much money. Same decisions, filled at each latency."
      actions={
        bestLatencyMs !== null ? (
          <StatusPill tone="good" dot>
            best: {bestLatencyMs}ms
          </StatusPill>
        ) : undefined
      }
    >
      <div className="space-y-5">
        {/* Bar chart: realized PnL by latency */}
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
            Realized PnL by latency
          </div>
          <BarChartCard
            data={bars}
            signedColors
            valueFormatter={(v) => usd(v)}
            yTickFormatter={(v) => usd(v, 0)}
            height={200}
          />
        </div>

        {/* Decay callout: PnL lost vs the 0ms account */}
        {decayTiers.length > 0 && (
          <div className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2.5">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
              <span className="text-warn">↓</span>
              PnL lost vs a 0ms account
            </div>
            <div className="flex flex-wrap gap-2">
              {decayTiers.map((d) => (
                <div
                  key={d.latency}
                  className="rounded-md border border-border bg-surface-2 px-3 py-1.5"
                >
                  <div className="text-[11px] text-muted">{d.latency}ms</div>
                  <div className={`tnum text-sm font-semibold ${signColor(d.delta)}`}>
                    {d.delta > 0 ? "+" : ""}
                    {usd(d.delta)}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted">
              Negative = that latency tier earned less than the instant (0ms)
              account. The gap is the cost of being slow.
            </p>
          </div>
        )}

        {/* Per-latency table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2 text-left">Latency</th>
                <th className="px-3 py-2 text-right">Decisions</th>
                <th className="px-3 py-2 text-right">Filled</th>
                <th className="px-3 py-2 text-right">Settled</th>
                <th className="px-3 py-2 text-right">Win %</th>
                <th className="px-3 py-2 text-right">Realized PnL</th>
                <th className="px-3 py-2 text-right">Avg slippage</th>
                <th className="px-3 py-2 text-right">Fill rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isBest =
                  bestLatencyMs !== null && r.latency_ms === bestLatencyMs;
                return (
                  <tr
                    key={r.latency_ms}
                    className={`border-b border-border/60 last:border-0 ${
                      isBest ? "bg-up/5" : ""
                    }`}
                  >
                    <td className="px-3 py-1.5 font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        {r.latency_ms}ms
                        {isBest && (
                          <StatusPill tone="good">best</StatusPill>
                        )}
                      </span>
                    </td>
                    <td className="tnum px-3 py-1.5 text-right text-muted">
                      {num(r.n_decisions, 0)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right text-muted">
                      {num(r.n_filled, 0)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right text-muted">
                      {num(r.n_settled, 0)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right">
                      {pct(r.win_rate)}
                    </td>
                    <td
                      className={`tnum px-3 py-1.5 text-right font-medium ${signColor(
                        r.realized_pnl
                      )}`}
                    >
                      {usd(r.realized_pnl)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right text-muted">
                      {price(r.avg_slippage_vs_decision)}
                    </td>
                    <td className="tnum px-3 py-1.5 text-right text-muted">
                      {pct(r.fill_rate)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-muted">
          Slippage is fill price minus decision price (in probability units).
          Higher latency generally means worse fills and missed decisions.
        </p>
      </div>
    </SectionCard>
  );
}
