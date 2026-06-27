import type { ReactNode } from "react";

export type PillTone = "good" | "bad" | "warn" | "neutral" | "accent";

const TONES: Record<PillTone, string> = {
  good: "bg-up/10 text-up border-up/30",
  bad: "bg-down/10 text-down border-down/30",
  warn: "bg-warn/10 text-warn border-warn/30",
  neutral: "bg-surface-2 text-muted border-border",
  accent: "bg-accent/10 text-accent border-accent/30",
};

export function StatusPill({
  tone = "neutral",
  children,
  dot = false,
  title,
}: {
  tone?: PillTone;
  children: ReactNode;
  /** show a leading status dot */
  dot?: boolean;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}
    >
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            tone === "good"
              ? "bg-up"
              : tone === "bad"
                ? "bg-down"
                : tone === "warn"
                  ? "bg-warn"
                  : tone === "accent"
                    ? "bg-accent"
                    : "bg-muted"
          }`}
        />
      )}
      {children}
    </span>
  );
}

/** Convenience: connected/disconnected feed pill. */
export function ConnectionPill({ connected }: { connected: boolean }) {
  return (
    <StatusPill tone={connected ? "good" : "bad"} dot>
      {connected ? "connected" : "down"}
    </StatusPill>
  );
}
