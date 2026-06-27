"use client";

import Link from "next/link";
import { useMemo } from "react";
import { getLiveMarkets } from "@/lib/api";
import { useApi, useNow } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { DataTable, type Column } from "@/components/DataTable";
import { StatusPill } from "@/components/StatusPill";
import { HealthBar } from "@/components/HealthBar";
import { AsyncBoundary } from "@/components/States";
import { countdown, price, int } from "@/lib/format";
import type { Market } from "@/lib/types";

export default function LiveMarketsPage() {
  const { data, loading, loaded, error, refetch } = useApi(
    getLiveMarkets,
    { markets: [] },
    [],
    5000
  );
  // Tick once a second so countdowns advance between 5s polls.
  const now = useNow(1000);

  const markets = data.markets;

  // Derive a per-row "seconds remaining" from end_time when present, else fall
  // back to the polled seconds_to_close (which only updates every 5s).
  const withRemaining = useMemo(
    () =>
      markets.map((m) => {
        let secs: number | null = m.seconds_to_close ?? null;
        if (m.end_time) {
          const end = new Date(m.end_time).getTime();
          if (!Number.isNaN(end)) secs = Math.round((end - now) / 1000);
        }
        return { ...m, _remaining: secs };
      }),
    [markets, now]
  );

  const cols: Column<Market & { _remaining: number | null }>[] = [
    {
      key: "asset",
      header: "Asset",
      cell: (m) => <span className="font-semibold">{m.asset}</span>,
    },
    {
      key: "window",
      header: "Window",
      cell: (m) => (
        <StatusPill tone="neutral">{m.window_minutes}m</StatusPill>
      ),
    },
    {
      key: "remaining",
      header: "Closes in",
      align: "right",
      cell: (m) => {
        const r = m._remaining;
        const tone =
          r === null ? "" : r <= 30 ? "text-down" : r <= 90 ? "text-warn" : "";
        return <span className={`tnum ${tone}`}>{countdown(r)}</span>;
      },
    },
    {
      key: "up",
      header: "Up",
      align: "right",
      cell: (m) => <span className="tnum text-up">{price(m.up_price)}</span>,
    },
    {
      key: "down",
      header: "Down",
      align: "right",
      cell: (m) => <span className="tnum text-down">{price(m.down_price)}</span>,
    },
    {
      key: "spread",
      header: "Spread",
      align: "right",
      cell: (m) => <span className="tnum">{price(m.spread)}</span>,
    },
    {
      key: "depth",
      header: "Depth (bid / ask)",
      align: "right",
      cell: (m) => (
        <span className="tnum text-muted">
          {int(m.bid_depth)} / {int(m.ask_depth)}
        </span>
      ),
    },
    {
      key: "health",
      header: "Data health",
      cell: (m) => <HealthBar value={m.data_health} />,
    },
    {
      key: "link",
      header: "",
      align: "right",
      cell: (m) => (
        <Link
          href={`/replay/${m.id}`}
          className="text-xs font-medium text-accent hover:underline"
        >
          replay →
        </Link>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Live Markets"
        subtitle="Currently-open 5m / 15m crypto Up-or-Down markets. Polls every 5s; countdowns tick locally."
        actions={
          <StatusPill tone={error ? "bad" : "good"} dot>
            {error ? "stale (API down)" : `${markets.length} live`}
          </StatusPill>
        }
      />

      <SectionCard
        title="Open markets"
        subtitle="Click a row to open its full replay (price, book, oracle, wallet trades)."
      >
        <AsyncBoundary
          loading={loading}
          loaded={loaded}
          error={error}
          isEmpty={markets.length === 0}
          onRetry={refetch}
          emptyTitle="No live markets"
          emptyBody="Either nothing is open right now or the discovery collector hasn't run yet (see README)."
        >
          <DataTable
            columns={cols}
            rows={withRemaining}
            rowKey={(m) => m.id}
          />
        </AsyncBoundary>
      </SectionCard>
    </div>
  );
}
