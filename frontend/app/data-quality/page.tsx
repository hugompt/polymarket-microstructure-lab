"use client";

import { getDataQuality } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { ConnectionPill, StatusPill } from "@/components/StatusPill";
import { DataTable, type Column } from "@/components/DataTable";
import { LoadingState } from "@/components/States";
import { ageAgo, int, utc } from "@/lib/format";
import type { ApiError, DataQualityFeed, MarketGap } from "@/lib/types";

export default function DataQualityPage() {
  const { data, loading, loaded, error } = useApi(
    getDataQuality,
    {
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
      api_errors: [],
    },
    [],
    10000
  );

  const t = data.totals;
  const cleanPct =
    t.raw > 0 ? `${((t.clean / t.raw) * 100).toFixed(1)}% of raw kept` : undefined;

  const feedCols: Column<DataQualityFeed>[] = [
    { key: "source", header: "Source", cell: (f) => <span className="font-mono text-xs">{f.source}</span> },
    { key: "asset", header: "Asset", cell: (f) => f.asset_symbol ?? "—" },
    {
      key: "token",
      header: "Token",
      cell: (f) => (
        <span className="font-mono text-xs text-muted">
          {f.token_id ? `${f.token_id.slice(0, 8)}…` : "—"}
        </span>
      ),
    },
    { key: "status", header: "Status", cell: (f) => <ConnectionPill connected={f.connected} /> },
    { key: "age", header: "Last msg", align: "right", cell: (f) => <span className="tnum">{ageAgo(f.last_message_age_s)}</span> },
    { key: "messages", header: "Msgs", align: "right", cell: (f) => <span className="tnum">{int(f.messages)}</span> },
    { key: "dups", header: "Dups", align: "right", cell: (f) => <span className="tnum">{int(f.duplicates)}</span> },
    { key: "stale", header: "Stale", align: "right", cell: (f) => <span className="tnum">{int(f.stale)}</span> },
    { key: "ooo", header: "OoO", align: "right", cell: (f) => <span className="tnum">{int(f.out_of_order)}</span> },
    { key: "reconnects", header: "Reconn.", align: "right", cell: (f) => <span className="tnum">{int(f.reconnects)}</span> },
    {
      key: "rejected",
      header: "Rejected",
      align: "right",
      cell: (f) => (
        <span className={`tnum ${f.rejected > 0 ? "text-down" : ""}`}>
          {int(f.rejected)}
        </span>
      ),
    },
  ];

  const gapCols: Column<MarketGap>[] = [
    { key: "market", header: "Market", cell: (g) => <span className="font-mono text-xs">{g.slug || g.market_id}</span> },
    { key: "expected", header: "Expected", align: "right", cell: (g) => <span className="tnum">{int(g.expected)}</span> },
    { key: "received", header: "Received", align: "right", cell: (g) => <span className="tnum">{int(g.received)}</span> },
    {
      key: "coverage",
      header: "Coverage",
      align: "right",
      cell: (g) => {
        const cov = g.expected > 0 ? g.received / g.expected : null;
        const tone = cov === null ? "" : cov >= 0.95 ? "text-up" : cov >= 0.8 ? "text-warn" : "text-down";
        return (
          <span className={`tnum ${tone}`}>
            {cov === null ? "—" : `${(cov * 100).toFixed(1)}%`}
          </span>
        );
      },
    },
    {
      key: "gaps",
      header: "Gaps",
      align: "right",
      cell: (g) => (
        <span className={`tnum ${g.gap_count > 0 ? "text-warn" : ""}`}>
          {int(g.gap_count)}
        </span>
      ),
    },
    { key: "maxgap", header: "Max gap", align: "right", cell: (g) => <span className="tnum">{g.max_gap_s === null ? "—" : `${int(g.max_gap_s)}s`}</span> },
  ];

  const errCols: Column<ApiError>[] = [
    { key: "ts", header: "Time (UTC)", cell: (e) => <span className="whitespace-nowrap">{utc(e.ts)}</span> },
    { key: "client", header: "Client", cell: (e) => <span className="font-mono text-xs">{e.client}</span> },
    { key: "path", header: "Path", cell: (e) => <span className="font-mono text-xs">{e.path}</span> },
    {
      key: "status",
      header: "Status",
      align: "right",
      cell: (e) => (
        <StatusPill tone={e.status_code && e.status_code >= 500 ? "bad" : "warn"}>
          {e.status_code ?? "—"}
        </StatusPill>
      ),
    },
    { key: "error", header: "Error", cell: (e) => <span className="text-muted">{e.error ?? "—"}</span> },
  ];

  return (
    <div>
      <PageHeader
        title="Data Quality"
        subtitle="Pipeline integrity: what was received vs kept, per-feed health, per-market gaps, and the API error log. Refreshes every 10s."
        actions={
          <StatusPill tone={error ? "bad" : "good"} dot>
            {error ? "API down" : "live"}
          </StatusPill>
        }
      />

      {loading && !loaded ? (
        <SectionCard>
          <LoadingState />
        </SectionCard>
      ) : (
        <div className="space-y-5">
          {/* Totals */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            <StatCard label="Raw events" value={int(t.raw)} hint={cleanPct} />
            <StatCard label="Clean events" value={int(t.clean)} tone="good" />
            <StatCard label="Duplicates" value={int(t.duplicates)} tone={t.duplicates > 0 ? "warn" : "default"} />
            <StatCard label="Stale" value={int(t.stale)} tone={t.stale > 0 ? "warn" : "default"} />
            <StatCard label="Out-of-order" value={int(t.out_of_order)} tone={t.out_of_order > 0 ? "warn" : "default"} />
            <StatCard label="Reconnects" value={int(t.reconnects)} />
            <StatCard label="Rejected" value={int(t.rejected)} tone={t.rejected > 0 ? "bad" : "default"} />
            <StatCard label="Gaps" value={int(t.gaps)} tone={t.gaps > 0 ? "warn" : "default"} />
          </div>

          {/* Feeds */}
          <SectionCard title="Per-feed health" subtitle="Connection and integrity counters per data source.">
            <DataTable
              columns={feedCols}
              rows={data.feeds}
              rowKey={(f, i) => `${f.source}-${f.token_id ?? i}`}
              empty="No feeds registered yet — start the collectors (see README)."
            />
          </SectionCard>

          {/* Gaps */}
          <SectionCard
            title="Per-market gap analysis"
            subtitle="Expected vs received snapshots per market. Low coverage means missing data — interpret that market's replay cautiously."
          >
            <DataTable
              columns={gapCols}
              rows={data.market_gaps}
              rowKey={(g) => g.market_id}
              empty="No gap data yet."
            />
          </SectionCard>

          {/* API errors */}
          <SectionCard
            title="API error log"
            subtitle="Recent upstream / internal API errors."
          >
            <DataTable
              columns={errCols}
              rows={data.api_errors}
              rowKey={(e, i) => `${e.ts}-${i}`}
              empty="No API errors logged. (Good.)"
            />
          </SectionCard>
        </div>
      )}
    </div>
  );
}
