// Display formatting helpers. Conservative: nulls/NaN never render as a number.

const DASH = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** USDC amount, e.g. "$1,234.50" / "-$8.00". null -> em dash. */
export function usd(v: number | null | undefined, decimals = 2): string {
  if (!isNum(v)) return DASH;
  const neg = v < 0;
  const abs = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${neg ? "-" : ""}$${abs}`;
}

/** Compact USDC for large volumes, e.g. "$50.0k", "$1.2M". */
export function usdCompact(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const neg = v < 0;
  const a = Math.abs(v);
  let s: string;
  if (a >= 1_000_000) s = `${(a / 1_000_000).toFixed(1)}M`;
  else if (a >= 1_000) s = `${(a / 1_000).toFixed(1)}k`;
  else s = a.toFixed(2);
  return `${neg ? "-" : ""}$${s}`;
}

/** Probability 0..1 -> "62.0%". */
export function pct(v: number | null | undefined, decimals = 1): string {
  if (!isNum(v)) return DASH;
  return `${(v * 100).toFixed(decimals)}%`;
}

/** Raw price 0..1 -> "0.620". */
export function price(v: number | null | undefined, decimals = 3): string {
  if (!isNum(v)) return DASH;
  return v.toFixed(decimals);
}

/** Plain integer with thousands separators. */
export function int(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  return Math.round(v).toLocaleString("en-US");
}

/** Number with fixed decimals (e.g. profit_factor). */
export function num(v: number | null | undefined, decimals = 2): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Seconds -> countdown. Rolls over hours/days so multi-hour values never
 * render as "1196:58". "d h:mm:ss" / "h:mm:ss" when ≥1h, else "m:ss".
 * Negative/closed -> "closed".
 */
export function countdown(seconds: number | null | undefined): string {
  if (!isNum(seconds)) return DASH;
  if (seconds <= 0) return "closed";
  const total = Math.floor(seconds);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = s.toString().padStart(2, "0");
  const mm = m.toString().padStart(2, "0");
  if (d > 0) return `${d}d ${h}:${mm}:${ss}`;
  if (h > 0) return `${h}:${mm}:${ss}`;
  return `${m}:${ss}`;
}

/** "12s ago" style for a seconds-age value. */
export function ageAgo(seconds: number | null | undefined): string {
  if (!isNum(seconds)) return "never";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

/** ISO string -> "2026-06-23 12:00:00 UTC". null -> em dash. */
export function utc(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(
    d.getUTCDate()
  )} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

/** ISO string -> "12:00:00" (UTC time only, for chart axes). */
export function utcTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

/** ISO string -> "06-23" (UTC date, for day axes). */
export function utcDay(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`;
}

/** Truncate a 0x address to 0x1234…cdef. */
export function shortAddr(addr: string | null | undefined): string {
  if (!addr) return DASH;
  if (addr.length <= 12) return addr;
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

/** Tailwind text color class for a signed number (gain/loss). */
export function signColor(v: number | null | undefined): string {
  if (!isNum(v) || v === 0) return "text-foreground";
  return v > 0 ? "text-up" : "text-down";
}
