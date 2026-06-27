import type { ReactNode } from "react";

/** Centered placeholder used for loading/error/empty states. */
function Placeholder({
  icon,
  title,
  body,
  tone = "muted",
  children,
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  tone?: "muted" | "bad";
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {icon && <div className="text-2xl">{icon}</div>}
      <div
        className={`text-sm font-medium ${
          tone === "bad" ? "text-down" : "text-foreground"
        }`}
      >
        {title}
      </div>
      {body && <div className="max-w-md text-sm text-muted">{body}</div>}
      {children}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 px-6 py-10 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: string;
  onRetry?: () => void;
}) {
  return (
    <Placeholder
      icon="⛔"
      tone="bad"
      title="Backend unreachable"
      body={
        <>
          <span className="block">
            Could not reach the API. Is it running on the configured base URL?
          </span>
          <code className="mt-2 block rounded bg-surface-2 px-2 py-1 text-xs text-muted">
            {error}
          </code>
        </>
      }
    >
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-1 rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground hover:border-accent/50"
        >
          Retry
        </button>
      )}
    </Placeholder>
  );
}

export function EmptyState({
  title = "No data yet",
  body = "Run the collectors to populate this view (see README).",
  icon = "∅",
}: {
  title?: string;
  body?: ReactNode;
  icon?: ReactNode;
}) {
  return <Placeholder icon={icon} title={title} body={body} />;
}

/**
 * Helper that picks the right state to render. If `error` is set AND there is
 * no usable data, show the error; if loading and not loaded, show loader; if
 * empty, show empty; otherwise render children.
 */
export function AsyncBoundary({
  loading,
  loaded,
  error,
  isEmpty,
  onRetry,
  emptyTitle,
  emptyBody,
  children,
}: {
  loading: boolean;
  loaded: boolean;
  error: string | null;
  isEmpty: boolean;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyBody?: ReactNode;
  children: ReactNode;
}) {
  if (loading && !loaded) return <LoadingState />;
  // Only surface a hard error when we genuinely have nothing to show.
  if (error && isEmpty) return <ErrorState error={error} onRetry={onRetry} />;
  if (isEmpty) return <EmptyState title={emptyTitle} body={emptyBody} />;
  return <>{children}</>;
}
