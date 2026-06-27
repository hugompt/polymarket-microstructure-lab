/**
 * CSV export link. Points at a backend `/api/export/...` URL (text/csv).
 * Uses a plain anchor with `download` so the browser handles the file; if the
 * backend is down the click simply fails gracefully (no app crash).
 */
export function ExportButton({
  href,
  label = "Export CSV",
}: {
  href: string;
  label?: string;
}) {
  return (
    <a
      href={href}
      download
      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground hover:border-accent/50 hover:text-accent"
    >
      <span aria-hidden>↓</span>
      {label}
    </a>
  );
}
