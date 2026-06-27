import { isNum, pct } from "@/lib/format";

/** Horizontal 0..1 data-health bar; color graded green/amber/red. */
export function HealthBar({ value }: { value: number | null | undefined }) {
  const v = isNum(value) ? Math.max(0, Math.min(1, value)) : null;
  const color =
    v === null
      ? "bg-border"
      : v >= 0.9
        ? "bg-up"
        : v >= 0.6
          ? "bg-warn"
          : "bg-down";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`h-full ${color}`}
          style={{ width: `${(v ?? 0) * 100}%` }}
        />
      </div>
      <span className="tnum text-xs text-muted">{v === null ? "—" : pct(v, 0)}</span>
    </div>
  );
}
