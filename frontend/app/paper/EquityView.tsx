"use client";

import { useMemo } from "react";
import { SectionCard } from "@/components/SectionCard";
import {
  TimeSeriesChart,
  type LineDef,
} from "@/components/charts/TimeSeriesChart";
import { SERIES_PALETTE } from "@/components/charts/chartTheme";
import { usd } from "@/lib/format";
import type { PaperEquityPoint } from "@/lib/types";

/**
 * Multi-line equity curve: one line per latency account. We merge the separate
 * per-latency series into a single row-per-timestamp dataset so Recharts can
 * draw aligned lines that share an X axis.
 */
export function EquityCurves({
  equityByLatency,
}: {
  equityByLatency: Record<string, PaperEquityPoint[]>;
}) {
  const { data, lines } = useMemo(() => {
    const latencies = Object.keys(equityByLatency)
      .map((k) => Number(k))
      .filter((n) => Number.isFinite(n))
      .sort((a, b) => a - b);

    // Build a map from epoch -> { xEpoch, lat_<ms>: pnl }.
    const byEpoch = new Map<number, Record<string, number | null>>();
    for (const lat of latencies) {
      const series = equityByLatency[String(lat)] ?? [];
      for (const pt of series) {
        const epoch = new Date(pt.t).getTime();
        if (Number.isNaN(epoch)) continue;
        let row = byEpoch.get(epoch);
        if (!row) {
          row = { xEpoch: epoch };
          byEpoch.set(epoch, row);
        }
        row[`lat_${lat}`] = pt.realized_pnl;
      }
    }

    const rows = Array.from(byEpoch.values()).sort(
      (a, b) => (a.xEpoch ?? 0)! - (b.xEpoch ?? 0)!
    );

    const lineDefs: LineDef[] = latencies.map((lat, i) => ({
      dataKey: `lat_${lat}`,
      name: `${lat}ms`,
      color: SERIES_PALETTE[i % SERIES_PALETTE.length],
    }));

    return { data: rows, lines: lineDefs };
  }, [equityByLatency]);

  const hasData = data.length > 0 && lines.length > 0;

  return (
    <SectionCard
      title="Equity curves by latency"
      subtitle="Realized PnL over time, one line per latency account. Faster accounts should sit on top."
    >
      {hasData ? (
        <>
          <TimeSeriesChart
            data={data}
            lines={lines}
            height={280}
            yTickFormatter={(v) => usd(v, 0)}
          />
          <div className="mt-2 flex flex-wrap gap-3">
            {lines.map((l) => (
              <span
                key={l.dataKey}
                className="inline-flex items-center gap-1.5 text-xs text-muted"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: l.color }}
                />
                {l.name}
              </span>
            ))}
          </div>
        </>
      ) : (
        <p className="px-1 py-6 text-center text-sm text-muted">
          No settled decisions yet. Equity curves appear once markets resolve.
        </p>
      )}
    </SectionCard>
  );
}
