"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getPaperOrders,
  getPaperSession,
  listPaperSessions,
  listPaperStrategies,
  startPaper,
  stopPaper,
} from "@/lib/api";
import { useApi, usePolling } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusPill } from "@/components/StatusPill";
import { WarningPanel } from "@/components/WarningPanel";
import { EmptyState, LoadingState } from "@/components/States";
import { num, usd, utc, signColor } from "@/lib/format";
import type {
  PaperOrder,
  PaperSessionDetail,
  PaperStartRequest,
  PaperStrategiesResponse,
  PaperSessionsResponse,
} from "@/lib/types";
import { LatencyComparison } from "./LatencyView";
import { EquityCurves } from "./EquityView";
import { OrdersTable } from "./OrdersView";

const ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"];
const WINDOWS = [5, 15];
const DEFAULT_LATENCIES = "0, 40, 100, 250, 500, 1000";
const FEE_SCENARIOS = ["conservative", "taker_like", "maker_like", "none"];
const MAX_DURATION = 7200;

export default function PaperTradingPage() {
  const strategies = useApi<PaperStrategiesResponse>(
    listPaperStrategies,
    { strategies: [] },
    []
  );
  // Poll the sessions list every 5s so newly-started / finished sessions show.
  const sessions = useApi<PaperSessionsResponse>(
    listPaperSessions,
    { sessions: [] },
    [],
    5000
  );

  // Form state
  const [strategy, setStrategy] = useState("");
  const [assets, setAssets] = useState<string[]>(["BTC"]);
  const [windows, setWindows] = useState<number[]>([5]);
  const [latencyText, setLatencyText] = useState(DEFAULT_LATENCIES);
  const [size, setSize] = useState(100);
  const [duration, setDuration] = useState(900);
  const [feeScenario, setFeeScenario] = useState("conservative");

  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [startNote, setStartNote] = useState<string | null>(null);

  // Selected session detail + orders
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PaperSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [stopping, setStopping] = useState(false);

  const effectiveStrategy =
    strategy || strategies.data.strategies[0]?.key || "";
  const selectedStrategyDef = strategies.data.strategies.find(
    (s) => s.key === effectiveStrategy
  );

  const parsedLatencies = parseLatencies(latencyText);
  const durationCapped = Math.min(Math.max(duration, 1), MAX_DURATION);

  // Auto-select the most recent session once the list first loads. This syncs
  // local selection to the externally-fetched list, not a render cascade.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (selectedId === null && sessions.data.sessions.length > 0) {
      setSelectedId(sessions.data.sessions[0].id);
    }
  }, [sessions.data.sessions, selectedId]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const loadDetail = useCallback(
    async (id: number, showSpinner: boolean) => {
      if (showSpinner) {
        setDetailLoading(true);
        setOrdersLoading(true);
      }
      const [d, o] = await Promise.all([
        getPaperSession(id),
        getPaperOrders(id),
      ]);
      setDetail(d.data);
      setOrders(o.data.orders);
      setDetailLoading(false);
      setOrdersLoading(false);
    },
    []
  );

  // Load detail whenever the selection changes. The clearing setState below is
  // a reset tied to an external selection change, not a synchronous cascade.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setOrders([]);
      return;
    }
    void loadDetail(selectedId, true);
  }, [selectedId, loadDetail]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Poll the selected session while it is running.
  const selectedSummary = sessions.data.sessions.find(
    (s) => s.id === selectedId
  );
  const isRunning =
    selectedSummary?.is_running === true || detail?.session?.is_running === true;
  usePolling(
    () => {
      if (selectedId !== null) void loadDetail(selectedId, false);
    },
    5000,
    isRunning
  );

  async function onStart(e: React.FormEvent) {
    e.preventDefault();
    setStarting(true);
    setStartError(null);
    setStartNote(null);
    const body: PaperStartRequest = {
      strategy: effectiveStrategy,
      assets,
      windows,
      latencies_ms: parsedLatencies,
      size,
      duration_s: durationCapped,
      fee_scenario: feeScenario,
      params: {},
    };
    const res = await startPaper(body);
    setStarting(false);
    if (res.error && res.data.session_id === null) {
      setStartError(res.error);
      return;
    }
    setStartNote(res.data.note || null);
    sessions.refetch();
    if (res.data.session_id !== null) {
      setSelectedId(res.data.session_id);
    }
  }

  async function onStop() {
    if (selectedId === null) return;
    setStopping(true);
    await stopPaper(selectedId);
    setStopping(false);
    sessions.refetch();
    void loadDetail(selectedId, false);
  }

  function toggle<T>(arr: T[], v: T, set: (a: T[]) => void) {
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  }

  const canStart =
    !starting &&
    effectiveStrategy !== "" &&
    assets.length > 0 &&
    windows.length > 0 &&
    parsedLatencies.length > 0;

  return (
    <div>
      <PageHeader
        title="Paper Trading"
        subtitle="Forward (live) paper trading. Runs a strategy against live markets and fills each decision at several latencies to show how many milliseconds cost how much money."
        actions={
          <StatusPill tone={isRunning ? "good" : "neutral"} dot>
            {isRunning ? "session running" : "idle"}
          </StatusPill>
        }
      />

      {/* Prominent simulation-only banner */}
      <div className="mb-5 rounded-lg border border-accent/40 bg-accent/5 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-accent">⚠</span>
          <h2 className="text-sm font-semibold text-foreground">
            FORWARD PAPER TRADING — SIMULATION ONLY. No real orders, no wallet,
            no keys.
          </h2>
        </div>
        <p className="mt-1 pl-6 text-xs text-muted">
          Runs a strategy live and fills each decision at several latencies to
          show how many milliseconds cost how much money.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[340px_1fr]">
        {/* Start form + sessions list */}
        <div className="space-y-5">
          <SectionCard title="Start a session">
            <form onSubmit={onStart} className="space-y-4">
              <Field label="Strategy">
                <select
                  value={effectiveStrategy}
                  onChange={(e) => setStrategy(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
                >
                  {strategies.data.strategies.length === 0 && (
                    <option value="">(no strategies available)</option>
                  )}
                  {strategies.data.strategies.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.name || s.key}
                    </option>
                  ))}
                </select>
                {selectedStrategyDef?.needs &&
                  selectedStrategyDef.needs.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted">
                      Needs: {selectedStrategyDef.needs.join(", ")}
                    </p>
                  )}
              </Field>

              <Field label="Assets">
                <div className="flex flex-wrap gap-1.5">
                  {ASSETS.map((a) => (
                    <Chip
                      key={a}
                      active={assets.includes(a)}
                      onClick={() => toggle(assets, a, setAssets)}
                    >
                      {a}
                    </Chip>
                  ))}
                </div>
              </Field>

              <Field label="Windows">
                <div className="flex flex-wrap gap-1.5">
                  {WINDOWS.map((w) => (
                    <Chip
                      key={w}
                      active={windows.includes(w)}
                      onClick={() => toggle(windows, w, setWindows)}
                    >
                      {w}m
                    </Chip>
                  ))}
                </div>
              </Field>

              <Field label="Latency grid (ms)">
                <input
                  type="text"
                  value={latencyText}
                  onChange={(e) => setLatencyText(e.target.value)}
                  placeholder={DEFAULT_LATENCIES}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm tnum"
                />
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {parsedLatencies.length > 0 ? (
                    parsedLatencies.map((l) => (
                      <span
                        key={l}
                        className="rounded border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] tnum text-muted"
                      >
                        {l}ms
                      </span>
                    ))
                  ) : (
                    <span className="text-[11px] text-warn">
                      Enter comma-separated latencies, e.g. {DEFAULT_LATENCIES}
                    </span>
                  )}
                </div>
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Size (USDC)">
                  <input
                    type="number"
                    min={1}
                    value={size}
                    onChange={(e) => setSize(Number(e.target.value))}
                    className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
                  />
                </Field>
                <Field label="Duration (s)">
                  <input
                    type="number"
                    min={1}
                    max={MAX_DURATION}
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                    className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
                  />
                </Field>
              </div>
              <p className="-mt-2 text-[11px] text-muted">
                Duration is capped at {num(MAX_DURATION, 0)}s.
                {durationCapped !== duration &&
                  ` Will run for ${num(durationCapped, 0)}s.`}
              </p>

              <Field label="Fee scenario">
                <select
                  value={feeScenario}
                  onChange={(e) => setFeeScenario(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
                >
                  {FEE_SCENARIOS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </Field>

              <button
                type="submit"
                disabled={!canStart}
                className="w-full rounded-md border border-accent/40 bg-accent/15 px-3 py-2 text-sm font-semibold text-accent hover:bg-accent/25 disabled:opacity-40"
              >
                {starting ? "Starting…" : "Start paper session"}
              </button>
              {(assets.length === 0 ||
                windows.length === 0 ||
                parsedLatencies.length === 0) && (
                <p className="text-[11px] text-warn">
                  Pick at least one asset, one window, and one latency.
                </p>
              )}
            </form>
          </SectionCard>

          {startError && (
            <WarningPanel title="Could not start session" tone="bad" items={[startError]} />
          )}
          {startNote && (
            <WarningPanel title="Session started" tone="info" items={[startNote]} />
          )}

          <SectionCard
            title="Sessions"
            subtitle="Click a session to inspect it."
            actions={
              <StatusPill tone="neutral">
                {sessions.data.sessions.length}
              </StatusPill>
            }
          >
            {sessions.loading && !sessions.loaded ? (
              <LoadingState />
            ) : sessions.data.sessions.length === 0 ? (
              <EmptyState
                title="No paper sessions yet"
                body={
                  <>
                    Start one above, or run{" "}
                    <code className="rounded bg-surface-2 px-1 py-0.5 text-xs">
                      python -m app paper-trade
                    </code>{" "}
                    from the CLI.
                  </>
                }
              />
            ) : (
              <ul className="space-y-1.5">
                {sessions.data.sessions.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(s.id)}
                      className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                        selectedId === s.id
                          ? "border-accent/50 bg-surface-2"
                          : "border-border hover:bg-surface-2/60"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">
                          #{s.id} {s.strategy_key}
                        </span>
                        <StatusPill
                          tone={s.is_running ? "good" : "neutral"}
                          dot={s.is_running}
                        >
                          {s.is_running ? "running" : s.status}
                        </StatusPill>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted">
                        <span>
                          {s.assets.join("/") || "—"} ·{" "}
                          {s.windows.map((w) => `${w}m`).join("/") || "—"}
                        </span>
                        {s.best_realized_pnl !== null && (
                          <span className={`tnum ${signColor(s.best_realized_pnl)}`}>
                            best {usd(s.best_realized_pnl)}
                            {s.best_latency_ms !== null
                              ? ` @ ${s.best_latency_ms}ms`
                              : ""}
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </div>

        {/* Selected session detail */}
        <div className="space-y-5">
          {selectedId === null ? (
            <SectionCard title="Session detail">
              <EmptyState
                title="No session selected"
                body="Start a session or pick one from the list to see the latency comparison."
              />
            </SectionCard>
          ) : detailLoading && !detail ? (
            <SectionCard title="Session detail">
              <LoadingState label="Loading session…" />
            </SectionCard>
          ) : (
            <>
              {/* Session header / stop control */}
              <SectionCard
                title={`Session #${selectedId}`}
                subtitle={
                  detail?.session
                    ? `${detail.session.strategy_key} · started ${utc(
                        detail.session.started_at
                      )}`
                    : undefined
                }
                actions={
                  <div className="flex items-center gap-2">
                    {isRunning && (
                      <StatusPill tone="good" dot>
                        live · polling 5s
                      </StatusPill>
                    )}
                    {isRunning && (
                      <button
                        type="button"
                        onClick={onStop}
                        disabled={stopping}
                        className="rounded-md border border-down/40 bg-down/10 px-2.5 py-1 text-xs font-medium text-down hover:bg-down/20 disabled:opacity-40"
                      >
                        {stopping ? "Stopping…" : "Stop"}
                      </button>
                    )}
                  </div>
                }
              >
                {detail?.session ? (
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
                    <Meta label="Status" value={detail.session.status} />
                    <Meta
                      label="Assets"
                      value={detail.session.assets.join(", ") || "—"}
                    />
                    <Meta
                      label="Windows"
                      value={
                        detail.session.windows.map((w) => `${w}m`).join(", ") ||
                        "—"
                      }
                    />
                    <Meta
                      label="Size"
                      value={
                        detail.session.size === null
                          ? "—"
                          : usd(detail.session.size)
                      }
                    />
                    <Meta
                      label="Latencies"
                      value={
                        detail.session.latency_grid_ms
                          .map((l) => `${l}ms`)
                          .join(", ") || "—"
                      }
                    />
                    <Meta
                      label="Fee scenario"
                      value={detail.session.fee_scenario || "—"}
                    />
                    <Meta
                      label="Stopped"
                      value={
                        detail.session.stopped_at
                          ? utc(detail.session.stopped_at)
                          : "—"
                      }
                    />
                  </div>
                ) : (
                  <p className="text-sm text-muted">
                    Session metadata unavailable (backend may be down).
                  </p>
                )}
              </SectionCard>

              {/* Warnings */}
              {detail && detail.warnings.length > 0 && (
                <WarningPanel
                  title="Warnings"
                  tone="warn"
                  items={detail.warnings}
                />
              )}

              {/* THE centerpiece: latency comparison */}
              <LatencyComparison
                byLatency={detail?.by_latency ?? []}
                decay={detail?.pnl_decay_vs_zero_latency ?? {}}
                bestLatencyMs={selectedSummary?.best_latency_ms ?? null}
              />

              {/* Equity curves */}
              <EquityCurves
                equityByLatency={detail?.equity_by_latency ?? {}}
              />

              {/* Orders */}
              <OrdersTable
                orders={orders}
                loading={ordersLoading}
                latencyGrid={
                  detail?.session?.latency_grid_ms ??
                  selectedSummary?.latency_grid_ms ??
                  []
                }
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** Parse "0, 40, 100" -> [0,40,100], deduped, sorted, non-negative ints. */
function parseLatencies(text: string): number[] {
  const set = new Set<number>();
  for (const part of text.split(/[,\s]+/)) {
    if (part === "") continue;
    const n = Number(part);
    if (Number.isFinite(n) && n >= 0) set.add(Math.round(n));
  }
  return Array.from(set).sort((a, b) => a - b);
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
        {label}
      </span>
      {children}
    </label>
  );
}

function Chip({
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
      className={`rounded-md border px-2.5 py-1 text-xs font-medium ${
        active
          ? "border-accent/50 bg-accent/15 text-accent"
          : "border-border bg-surface-2 text-muted hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted">
        {label}
      </div>
      <div className="text-sm text-foreground">{value}</div>
    </div>
  );
}
