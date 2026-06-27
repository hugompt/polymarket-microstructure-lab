"use client";

import { getHealth, emptyHealth } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { SectionCard } from "@/components/SectionCard";
import { WarningPanel } from "@/components/WarningPanel";
import { DataTable, type Column } from "@/components/DataTable";
import { ConnectionPill, StatusPill } from "@/components/StatusPill";
import { LoadingState } from "@/components/States";
import { ageAgo, int, utc } from "@/lib/format";
import type { Feed } from "@/lib/types";

export default function OverviewPage() {
  const { data: health, loading, loaded, error } = useApi(
    getHealth,
    emptyHealth(),
    [],
    5000
  );

  const c = health.counts;

  // Group feeds by source family for the collector/WS/RTDS health summary.
  const feedFamilies = summarizeFeeds(health.feeds);

  const feedCols: Column<Feed>[] = [
    { key: "source", header: "Feed", cell: (f) => <span className="font-mono text-xs">{f.source}</span> },
    {
      key: "status",
      header: "Status",
      cell: (f) => <ConnectionPill connected={f.connected} />,
    },
    {
      key: "age",
      header: "Last msg",
      align: "right",
      cell: (f) => <span className="tnum">{ageAgo(f.last_message_age_s)}</span>,
    },
    { key: "messages", header: "Messages", align: "right", cell: (f) => <span className="tnum">{int(f.messages)}</span> },
    { key: "duplicates", header: "Dups", align: "right", cell: (f) => <span className="tnum">{int(f.duplicates)}</span> },
    { key: "stale", header: "Stale", align: "right", cell: (f) => <span className="tnum">{int(f.stale)}</span> },
    { key: "ooo", header: "Out-of-order", align: "right", cell: (f) => <span className="tnum">{int(f.out_of_order)}</span> },
    { key: "reconnects", header: "Reconnects", align: "right", cell: (f) => <span className="tnum">{int(f.reconnects)}</span> },
  ];

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="System health and collection counts. Numbers reflect the live backend; nothing here implies the bot is profitable."
        actions={
          <StatusPill tone={error ? "bad" : health.db_ok ? "good" : "warn"} dot>
            {error ? "API down" : health.db_ok ? "DB ok" : "DB unknown"}
          </StatusPill>
        }
      />

      {loading && !loaded ? (
        <SectionCard>
          <LoadingState />
        </SectionCard>
      ) : (
        <div className="space-y-5">
          {/* Warnings first — most important signal on this page */}
          <WarningPanel
            title="Health warnings"
            items={
              error
                ? [`Backend unreachable: ${error}`, ...health.warnings]
                : health.warnings
            }
            tone={error ? "bad" : "warn"}
            emptyMessage="No active warnings. All configured feeds reporting and data is fresh."
          />

          {/* Top counts */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Active markets" value={int(c.live_markets)} />
            <StatCard label="Upcoming" value={int(c.upcoming_markets)} />
            <StatCard
              label="Markets tracked"
              value={int(c.markets)}
              hint="total, all time"
            />
            <StatCard
              label="Snapshots today"
              value={int(c.orderbook_snapshots_today)}
              hint="order-book snapshots"
            />
            <StatCard
              label="Ticks today"
              value={int(c.ticks_today)}
              hint="price ticks"
            />
            <StatCard
              label="API errors today"
              value={int(c.api_errors_today)}
              tone={c.api_errors_today > 0 ? "bad" : "default"}
            />
          </div>

          {/* Feed family health */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {feedFamilies.map((fam) => (
              <StatCard
                key={fam.label}
                label={fam.label}
                value={
                  <span className={fam.connected > 0 ? "text-up" : "text-down"}>
                    {fam.connected}/{fam.total}
                  </span>
                }
                hint={
                  fam.total === 0
                    ? "no feeds of this type registered"
                    : "feeds connected"
                }
                sub={fam.total > 0 ? <>last msg {ageAgo(fam.minAge)}</> : null}
              />
            ))}
          </div>

          {/* Sync times + budget */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Last discovery"
              value={<span className="text-base">{utc(health.last_discovery_at)}</span>}
            />
            <StatCard
              label="Last wallet sync"
              value={<span className="text-base">{utc(health.last_wallet_sync_at)}</span>}
            />
            <StatCard
              label="Backend time"
              value={<span className="text-base">{utc(health.time_utc)}</span>}
            />
            <StatCard
              label="Request budget left"
              value={int(health.request_budget_remaining)}
              hint="remaining API calls in window"
            />
          </div>

          {/* Per-feed table */}
          <SectionCard
            title="Feeds"
            subtitle="Per-source connection health from /api/health."
          >
            <DataTable
              columns={feedCols}
              rows={health.feeds}
              rowKey={(f, i) => `${f.source}-${i}`}
              empty="No feeds connected — start the collectors (CLOB WS, RTDS) to populate this."
            />
          </SectionCard>
        </div>
      )}
    </div>
  );
}

/** Bucket feeds into Collector / WebSocket / RTDS families heuristically. */
function summarizeFeeds(feeds: Feed[]) {
  const families: { label: string; match: (s: string) => boolean }[] = [
    { label: "CLOB WebSocket", match: (s) => /clob|ws|book|orderbook/i.test(s) },
    {
      label: "RTDS / oracle",
      match: (s) => /rtds|chainlink|binance|oracle|price/i.test(s),
    },
    { label: "Collector / other", match: () => true },
  ];
  const assigned = new Set<number>();
  return families.map((fam) => {
    const members = feeds.filter((f, i) => {
      if (assigned.has(i)) return false;
      if (fam.match(f.source)) {
        assigned.add(i);
        return true;
      }
      return false;
    });
    const connected = members.filter((m) => m.connected).length;
    const ages = members
      .map((m) => m.last_message_age_s)
      .filter((a): a is number => typeof a === "number");
    return {
      label: fam.label,
      total: members.length,
      connected,
      minAge: ages.length ? Math.min(...ages) : null,
    };
  });
}
