"use client";

import type { StrategyRunMetric } from "@/lib/types";
import { num, pct, usd } from "@/lib/format";

// Metrics are backend-defined (open shape). We surface a curated set in the
// side-by-side comparison and dump everything else in a table.
const HEADLINE: { key: string; label: string; fmt: (v: number) => string; higherBetter: boolean }[] = [
  { key: "net_pnl", label: "Net PnL", fmt: (v) => usd(v), higherBetter: true },
  { key: "gross_pnl", label: "Gross PnL", fmt: (v) => usd(v), higherBetter: true },
  { key: "win_rate", label: "Win rate", fmt: (v) => pct(v), higherBetter: true },
  { key: "profit_factor", label: "Profit factor", fmt: (v) => num(v), higherBetter: true },
  { key: "sharpe_like", label: "Sharpe", fmt: (v) => num(v), higherBetter: true },
  { key: "max_drawdown", label: "Max drawdown", fmt: (v) => usd(v), higherBetter: true },
  { key: "n_filled", label: "Trades filled", fmt: (v) => num(v, 0), higherBetter: false },
];

function n(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Side-by-side strategy vs random baseline for headline metrics. */
export function MetricsCompare({
  metrics,
  vsRandom,
}: {
  metrics: StrategyRunMetric;
  vsRandom: StrategyRunMetric;
}) {
  const present = HEADLINE.filter(
    (h) => n(metrics[h.key]) !== null || n(vsRandom[h.key]) !== null
  );

  if (present.length === 0) {
    return (
      <p className="text-sm text-muted">
        No comparable headline metrics returned by the backend for this run.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="px-3 py-2 text-left">Metric</th>
            <th className="px-3 py-2 text-right">Strategy</th>
            <th className="px-3 py-2 text-right">Random baseline</th>
            <th className="px-3 py-2 text-right">Δ</th>
          </tr>
        </thead>
        <tbody>
          {present.map((h) => {
            const a = n(metrics[h.key]);
            const b = n(vsRandom[h.key]);
            const delta = a !== null && b !== null ? a - b : null;
            const better =
              delta === null
                ? null
                : h.higherBetter
                  ? delta > 0
                  : delta < 0;
            return (
              <tr key={h.key} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-1.5 text-foreground">{h.label}</td>
                <td className="tnum px-3 py-1.5 text-right font-medium">
                  {a === null ? "—" : h.fmt(a)}
                </td>
                <td className="tnum px-3 py-1.5 text-right text-muted">
                  {b === null ? "—" : h.fmt(b)}
                </td>
                <td
                  className={`tnum px-3 py-1.5 text-right ${
                    better === null
                      ? "text-muted"
                      : better
                        ? "text-up"
                        : "text-down"
                  }`}
                >
                  {delta === null ? "—" : h.fmt(delta)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-muted">
        Δ is strategy minus random. A strategy that can&apos;t clearly beat a coin
        flip after fees has no demonstrated edge.
      </p>
    </div>
  );
}

/** Full dump of every metric key the backend returned. */
export function MetricsTable({
  title,
  metrics,
}: {
  title: string;
  metrics: StrategyRunMetric;
}) {
  const entries = Object.entries(metrics).filter(
    ([k]) => k !== "sample_warning"
  );
  if (entries.length === 0) return null;
  return (
    <details className="rounded-md border border-border bg-surface-2/40">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted">
        {title}
      </summary>
      <div className="overflow-x-auto px-3 pb-3">
        <table className="w-full text-sm">
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k} className="border-b border-border/40 last:border-0">
                <td className="py-1 pr-4 font-mono text-xs text-muted">{k}</td>
                <td className="tnum py-1 text-right">{fmt(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return num(v, 4).replace(/\.?0+$/, "");
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}
