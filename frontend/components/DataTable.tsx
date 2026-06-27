import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** cell renderer */
  cell: (row: T, index: number) => ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  /** header className */
  headClassName?: string;
}

/**
 * Dense, dark-friendly table. Renders an empty-row message when `rows` is
 * empty. Numeric columns should use align="right" + the `tnum` class for
 * tabular figures.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty = "No rows.",
  dense = true,
  stickyHeader = false,
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string | number;
  empty?: ReactNode;
  dense?: boolean;
  stickyHeader?: boolean;
  onRowClick?: (row: T) => void;
}) {
  const pad = dense ? "px-3 py-1.5" : "px-4 py-2.5";
  const alignClass = (a?: Column<T>["align"]) =>
    a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead
          className={`${
            stickyHeader ? "sticky top-0 z-10" : ""
          } bg-surface-2`}
        >
          <tr className="border-b border-border">
            {columns.map((c) => (
              <th
                key={c.key}
                className={`${pad} text-xs font-medium uppercase tracking-wide text-muted ${alignClass(
                  c.align
                )} ${c.headClassName || ""}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-sm text-muted"
              >
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={rowKey(row, i)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`border-b border-border/60 last:border-0 ${
                  onRowClick
                    ? "cursor-pointer hover:bg-surface-2"
                    : "hover:bg-surface-2/50"
                }`}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`${pad} ${alignClass(c.align)} ${
                      c.className || ""
                    }`}
                  >
                    {c.cell(row, i)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
