"use client";

import { useState } from "react";
import {
  exportStrategyRunUrl,
  getStrategyRun,
  listStrategies,
  listStrategyRuns,
  runStrategy,
} from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusPill } from "@/components/StatusPill";
import { WarningPanel } from "@/components/WarningPanel";
import { ExportButton } from "@/components/ExportButton";
import { EmptyState, LoadingState } from "@/components/States";
import { MetricsCompare, MetricsTable } from "./MetricsView";
import { num, utc } from "@/lib/format";
import type {
  StrategiesResponse,
  StrategyRunDetail,
  StrategyRunRequest,
  StrategyRunResult,
  StrategyRunsResponse,
} from "@/lib/types";

const ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"];
const WINDOWS = [5, 15];
const LATENCIES = [0, 40, 100, 250, 500, 1000];
const FILL_MODELS = [
  "optimistic",
  "realistic",
  "conservative",
  "taker",
  "maker",
];
const FEE_SCENARIOS = ["maker_like", "taker_like", "conservative"];

export default function StrategyPage() {
  const strategies = useApi<StrategiesResponse>(
    listStrategies,
    { strategies: [] },
    []
  );
  const runs = useApi<StrategyRunsResponse>(
    listStrategyRuns,
    { runs: [] },
    []
  );

  // Form state
  const [strategy, setStrategy] = useState("");
  const [assets, setAssets] = useState<string[]>(["BTC"]);
  const [windows, setWindows] = useState<number[]>([5]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [latency, setLatency] = useState(100);
  const [fillModel, setFillModel] = useState("realistic");
  const [feeScenario, setFeeScenario] = useState("conservative");
  const [size, setSize] = useState(100);

  // Run state
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<StrategyRunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // Selected past run detail
  const [detail, setDetail] = useState<StrategyRunDetail | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const effectiveStrategy =
    strategy || strategies.data.strategies[0]?.key || "random";

  async function onRun(e: React.FormEvent) {
    e.preventDefault();
    setRunning(true);
    setRunError(null);
    const body: StrategyRunRequest = {
      strategy: effectiveStrategy,
      assets,
      windows,
      date_from: dateFrom || null,
      date_to: dateTo || null,
      latency_ms: latency,
      fill_model: fillModel,
      fee_scenario: feeScenario,
      size,
      params: {},
    };
    const res = await runStrategy(body);
    setRunning(false);
    if (res.error && res.data.run_id === null) {
      setRunError(res.error);
      setResult(null);
    } else {
      setResult(res.data);
      setDetail(null);
      setDetailId(null);
      runs.refetch();
    }
  }

  async function openRun(id: number) {
    setDetailId(id);
    setDetailLoading(true);
    setResult(null);
    const res = await getStrategyRun(id);
    setDetail(res.data);
    setDetailLoading(false);
  }

  function toggle<T>(arr: T[], v: T, set: (a: T[]) => void) {
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  }

  return (
    <div>
      <PageHeader
        title="Strategy Lab"
        subtitle="Backtest a strategy against the recorded order flow and compare it to a random baseline. Small samples prove nothing — watch for the low-sample warning."
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[340px_1fr]">
        {/* Form */}
        <SectionCard title="Configure run">
          <form onSubmit={onRun} className="space-y-4">
            <Field label="Strategy">
              <select
                value={effectiveStrategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
              >
                {strategies.data.strategies.length === 0 && (
                  <option value="random">random (baseline)</option>
                )}
                {strategies.data.strategies.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.name || s.key}
                  </option>
                ))}
              </select>
              {strategies.data.strategies.find(
                (s) => s.key === effectiveStrategy
              )?.description && (
                <p className="mt-1 text-[11px] text-muted">
                  {
                    strategies.data.strategies.find(
                      (s) => s.key === effectiveStrategy
                    )?.description
                  }
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

            <div className="grid grid-cols-2 gap-3">
              <Field label="Date from">
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
                />
              </Field>
              <Field label="Date to">
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
                />
              </Field>
            </div>

            <Field label="Latency (ms)">
              <select
                value={latency}
                onChange={(e) => setLatency(Number(e.target.value))}
                className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
              >
                {LATENCIES.map((l) => (
                  <option key={l} value={l}>
                    {l} ms
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Fill model">
              <select
                value={fillModel}
                onChange={(e) => setFillModel(e.target.value)}
                className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
              >
                {FILL_MODELS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </Field>

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

            <Field label="Size (USDC per trade)">
              <input
                type="number"
                min={1}
                value={size}
                onChange={(e) => setSize(Number(e.target.value))}
                className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm"
              />
            </Field>

            <button
              type="submit"
              disabled={running || assets.length === 0 || windows.length === 0}
              className="w-full rounded-md border border-accent/40 bg-accent/15 px-3 py-2 text-sm font-semibold text-accent hover:bg-accent/25 disabled:opacity-40"
            >
              {running ? "Running…" : "Run backtest"}
            </button>
            {(assets.length === 0 || windows.length === 0) && (
              <p className="text-[11px] text-warn">
                Select at least one asset and one window.
              </p>
            )}
          </form>
        </SectionCard>

        {/* Results + history */}
        <div className="space-y-5">
          {runError && (
            <WarningPanel
              title="Run failed"
              tone="bad"
              items={[runError]}
            />
          )}

          {running && (
            <SectionCard title="Running backtest">
              <LoadingState label="Simulating against recorded flow…" />
            </SectionCard>
          )}

          {/* Fresh run result */}
          {result && !running && (
            <ResultView result={result} />
          )}

          {/* Past run detail */}
          {detailId !== null && (
            <SectionCard
              title={`Run #${detailId}`}
              actions={<ExportButton href={exportStrategyRunUrl(detailId)} />}
            >
              {detailLoading ? (
                <LoadingState />
              ) : detail ? (
                <div className="space-y-4">
                  <MetricsCompare
                    metrics={detail.metrics}
                    vsRandom={detail.vs_random}
                  />
                  <MetricsTable title="All metrics" metrics={detail.metrics} />
                  {detail.trades.length > 0 && (
                    <p className="text-xs text-muted">
                      {num(detail.trades.length, 0)} simulated trades in this run.
                    </p>
                  )}
                </div>
              ) : (
                <EmptyState title="No detail" body="This run could not be loaded." />
              )}
            </SectionCard>
          )}

          {/* Past runs list */}
          <SectionCard
            title="Past runs"
            subtitle="Click a run to inspect its metrics."
            actions={
              <StatusPill tone="neutral">
                {runs.data.runs.length} runs
              </StatusPill>
            }
          >
            {runs.loading && !runs.loaded ? (
              <LoadingState />
            ) : runs.data.runs.length === 0 ? (
              <EmptyState
                title="No runs yet"
                body="Configure a backtest on the left and run it."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-3 py-2 text-left">#</th>
                      <th className="px-3 py-2 text-left">Strategy</th>
                      <th className="px-3 py-2 text-left">Created</th>
                      <th className="px-3 py-2 text-right">Net PnL</th>
                      <th className="px-3 py-2 text-right">Win %</th>
                      <th className="px-3 py-2 text-right">Filled</th>
                      <th className="px-3 py-2 text-left">Sample</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.data.runs.map((r) => (
                      <tr
                        key={r.id}
                        onClick={() => openRun(r.id)}
                        className={`cursor-pointer border-b border-border/60 last:border-0 hover:bg-surface-2 ${
                          detailId === r.id ? "bg-surface-2" : ""
                        }`}
                      >
                        <td className="px-3 py-1.5">{r.id}</td>
                        <td className="px-3 py-1.5">{r.strategy_key}</td>
                        <td className="px-3 py-1.5 text-muted">
                          {utc(r.created_at)}
                        </td>
                        <td
                          className={`tnum px-3 py-1.5 text-right ${
                            (r.net_pnl ?? 0) >= 0 ? "text-up" : "text-down"
                          }`}
                        >
                          {r.net_pnl === null ? "—" : num(r.net_pnl)}
                        </td>
                        <td className="tnum px-3 py-1.5 text-right">
                          {r.win_rate === null
                            ? "—"
                            : `${(r.win_rate * 100).toFixed(1)}%`}
                        </td>
                        <td className="tnum px-3 py-1.5 text-right">
                          {r.n_filled === null ? "—" : num(r.n_filled, 0)}
                        </td>
                        <td className="px-3 py-1.5">
                          {r.sample_warning ? (
                            <StatusPill tone="warn">low sample</StatusPill>
                          ) : (
                            <StatusPill tone="good">ok</StatusPill>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

function ResultView({ result }: { result: StrategyRunResult }) {
  const sampleWarning =
    result.metrics?.sample_warning === true ||
    (typeof result.metrics?.sample_warning === "boolean" &&
      result.metrics.sample_warning);
  return (
    <SectionCard
      title="Latest run"
      subtitle={result.run_id !== null ? `Run #${result.run_id}` : undefined}
      actions={
        result.run_id !== null ? (
          <ExportButton href={exportStrategyRunUrl(result.run_id)} />
        ) : undefined
      }
    >
      <div className="space-y-4">
        {sampleWarning && (
          <div className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm font-medium text-warn">
            ⚠ Low sample size — not statistically meaningful. Do not draw
            conclusions from this run.
          </div>
        )}
        {result.warnings.length > 0 && (
          <WarningPanel title="Run warnings" items={result.warnings} />
        )}
        <MetricsCompare metrics={result.metrics} vsRandom={result.vs_random} />
        <MetricsTable title="All metrics" metrics={result.metrics} />
      </div>
    </SectionCard>
  );
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
