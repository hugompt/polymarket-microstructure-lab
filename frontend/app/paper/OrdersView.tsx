"use client";

import { useMemo, useState } from "react";
import { SectionCard } from "@/components/SectionCard";
import { StatusPill } from "@/components/StatusPill";
import { DataTable, type Column } from "@/components/DataTable";
import { LoadingState } from "@/components/States";
import { price, usd, utcTime, signColor } from "@/lib/format";
import type { PaperOrder } from "@/lib/types";

const PAGE = 50;

/**
 * Per-decision order table. Shows decision_price vs fill_price and slippage so
 * the latency effect is visible at the individual-order level. Filterable by
 * latency, capped/paginated client-side.
 */
export function OrdersTable({
  orders,
  loading,
  latencyGrid,
}: {
  orders: PaperOrder[];
  loading: boolean;
  latencyGrid: number[];
}) {
  const [latencyFilter, setLatencyFilter] = useState<number | null>(null);
  const [visible, setVisible] = useState(PAGE);

  const filtered = useMemo(
    () =>
      latencyFilter === null
        ? orders
        : orders.filter((o) => o.latency_ms === latencyFilter),
    [orders, latencyFilter]
  );
  const shown = filtered.slice(0, visible);

  const cols: Column<PaperOrder>[] = [
    {
      key: "ts",
      header: "Decision",
      cell: (o) => (
        <span className="tnum text-muted">{utcTime(o.decision_ts)}</span>
      ),
    },
    {
      key: "lat",
      header: "Latency",
      align: "right",
      cell: (o) => <span className="tnum">{o.latency_ms}ms</span>,
    },
    {
      key: "asset",
      header: "Asset",
      cell: (o) => (
        <span className="font-medium">
          {o.asset}{" "}
          <span className="text-muted">{o.window_minutes}m</span>
        </span>
      ),
    },
    {
      key: "outcome",
      header: "Outcome",
      cell: (o) => <span className="text-muted">{o.outcome}</span>,
    },
    {
      key: "dprice",
      header: "Decision px",
      align: "right",
      cell: (o) => <span className="tnum">{price(o.decision_price)}</span>,
    },
    {
      key: "fprice",
      header: "Fill px",
      align: "right",
      cell: (o) => <span className="tnum">{price(o.fill_price)}</span>,
    },
    {
      key: "slip",
      header: "Slippage",
      align: "right",
      cell: (o) => (
        <span
          className={`tnum ${
            o.slippage_vs_decision === null
              ? "text-muted"
              : o.slippage_vs_decision > 0
                ? "text-down"
                : o.slippage_vs_decision < 0
                  ? "text-up"
                  : "text-muted"
          }`}
        >
          {price(o.slippage_vs_decision)}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (o) => <StatusPill tone={statusTone(o.status)}>{o.status}</StatusPill>,
    },
    {
      key: "won",
      header: "Result",
      cell: (o) =>
        o.won === null ? (
          <span className="text-muted">—</span>
        ) : o.won ? (
          <StatusPill tone="good">won</StatusPill>
        ) : (
          <StatusPill tone="bad">lost</StatusPill>
        ),
    },
    {
      key: "pnl",
      header: "PnL",
      align: "right",
      cell: (o) => (
        <span className={`tnum ${signColor(o.pnl)}`}>
          {o.pnl === null ? "—" : usd(o.pnl)}
        </span>
      ),
    },
  ];

  return (
    <SectionCard
      title="Orders"
      subtitle="Every simulated decision across all latency accounts. Decision price vs fill price exposes the latency cost per order."
      actions={
        <span className="text-xs text-muted">
          {filtered.length} order{filtered.length === 1 ? "" : "s"}
        </span>
      }
    >
      {loading && orders.length === 0 ? (
        <LoadingState label="Loading orders…" />
      ) : (
        <div className="space-y-3">
          {/* Latency filter chips */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[11px] uppercase tracking-wide text-muted">
              Latency
            </span>
            <FilterChip
              active={latencyFilter === null}
              onClick={() => {
                setLatencyFilter(null);
                setVisible(PAGE);
              }}
            >
              all
            </FilterChip>
            {latencyGrid.map((l) => (
              <FilterChip
                key={l}
                active={latencyFilter === l}
                onClick={() => {
                  setLatencyFilter(l);
                  setVisible(PAGE);
                }}
              >
                {l}ms
              </FilterChip>
            ))}
          </div>

          <DataTable
            columns={cols}
            rows={shown}
            rowKey={(o, i) => `${o.decision_id}-${o.latency_ms}-${i}`}
            empty="No orders yet for this session."
          />

          {filtered.length > visible && (
            <button
              type="button"
              onClick={() => setVisible((v) => v + PAGE)}
              className="w-full rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-muted hover:text-foreground"
            >
              Show more ({filtered.length - visible} remaining)
            </button>
          )}
        </div>
      )}
    </SectionCard>
  );
}

function statusTone(status: string): "good" | "bad" | "warn" | "neutral" | "accent" {
  const s = status.toLowerCase();
  if (s.includes("settled") || s.includes("won")) return "good";
  if (s.includes("miss") || s.includes("lost") || s.includes("reject")) return "bad";
  if (s.includes("pending") || s.includes("open")) return "accent";
  return "neutral";
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
        active
          ? "border-accent/50 bg-accent/15 text-accent"
          : "border-border bg-surface-2 text-muted hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}
