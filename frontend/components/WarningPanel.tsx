import type { ReactNode } from "react";

type Tone = "warn" | "bad" | "info";

const TONE_CLASS: Record<Tone, string> = {
  warn: "border-warn/40 bg-warn/5",
  bad: "border-down/40 bg-down/5",
  info: "border-accent/40 bg-accent/5",
};
const ICON_CLASS: Record<Tone, string> = {
  warn: "text-warn",
  bad: "text-down",
  info: "text-accent",
};

/**
 * Prominent callout for health.warnings / wallet warnings / skeptic_notes.
 * Renders nothing when there are no items (unless `showWhenEmpty`).
 */
export function WarningPanel({
  title,
  items,
  tone = "warn",
  emptyMessage,
  icon = "⚠",
  children,
}: {
  title: string;
  items?: string[];
  tone?: Tone;
  /** message shown when items is empty; omit to render nothing when empty */
  emptyMessage?: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  const list = items ?? [];
  if (list.length === 0 && !emptyMessage && !children) return null;

  return (
    <div className={`rounded-lg border px-4 py-3 ${TONE_CLASS[tone]}`}>
      <div className="flex items-center gap-2">
        <span className={`text-sm ${ICON_CLASS[tone]}`}>{icon}</span>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {list.length > 0 && (
          <span className="text-xs text-muted">({list.length})</span>
        )}
      </div>
      {list.length > 0 ? (
        <ul className="mt-2 space-y-1.5 pl-1">
          {list.map((w, i) => (
            <li key={i} className="flex gap-2 text-sm text-foreground/90">
              <span className={ICON_CLASS[tone]}>•</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      ) : emptyMessage ? (
        <p className="mt-1.5 text-sm text-muted">{emptyMessage}</p>
      ) : null}
      {children}
    </div>
  );
}
