import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  hint,
  sub,
  tone = "default",
  className = "",
}: {
  label: ReactNode;
  value: ReactNode;
  /** small clarifying note under the value (e.g. source / "not profit") */
  hint?: ReactNode;
  /** secondary line, e.g. a delta */
  sub?: ReactNode;
  tone?: "default" | "good" | "bad" | "warn";
  className?: string;
}) {
  const valueColor =
    tone === "good"
      ? "text-up"
      : tone === "bad"
        ? "text-down"
        : tone === "warn"
          ? "text-warn"
          : "text-foreground";
  return (
    <div
      className={`rounded-lg border border-border bg-surface px-4 py-3 ${className}`}
    >
      <div className="text-xs font-medium uppercase tracking-wide text-muted">
        {label}
      </div>
      <div className={`tnum mt-1 text-2xl font-semibold ${valueColor}`}>
        {value}
      </div>
      {sub && <div className="tnum mt-0.5 text-xs text-muted">{sub}</div>}
      {hint && <div className="mt-1.5 text-[11px] leading-tight text-muted">{hint}</div>}
    </div>
  );
}
