"use client";

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART, axisStyle, tooltipStyle } from "./chartTheme";

export interface BarDatum {
  label: string;
  value: number;
  /** optional secondary tooltip fields */
  [key: string]: string | number;
}

/**
 * Categorical bar chart. When `signedColors` is true, positive bars are green
 * and negative bars red (used for PnL breakdowns). Otherwise a single accent
 * color (used for distributions / counts).
 */
export function BarChartCard({
  data,
  height = 220,
  signedColors = false,
  color = CHART.accent,
  valueFormatter,
  yTickFormatter,
  angledLabels = false,
}: {
  data: BarDatum[];
  height?: number;
  signedColors?: boolean;
  color?: string;
  valueFormatter?: (v: number) => string;
  yTickFormatter?: (v: number) => string;
  angledLabels?: boolean;
}) {
  // Pre-compute a SAFE static Y domain. Anchoring at 0 and guaranteeing min < max avoids
  // Recharts emitting "Received NaN for the height attribute": an all-zero dataset would
  // otherwise collapse the scale, and a function-form domain can be invoked with undefined on
  // first render (Math.min(0, undefined) === NaN), which poisons the whole chart.
  const values = data.map((d) => Number(d.value)).filter((v) => Number.isFinite(v));
  const lo = Math.min(0, ...(values.length ? values : [0]));
  const hiRaw = Math.max(0, ...(values.length ? values : [0]));
  const yDomain: [number, number] = [lo, hiRaw > lo ? hiRaw : lo + 1];

  return (
    <ResponsiveContainer width="100%" height={height} minWidth={0}>
      <BarChart
        data={data}
        margin={{ top: 8, right: 12, left: 0, bottom: angledLabels ? 28 : 4 }}
      >
        <CartesianGrid stroke={CHART.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="label"
          tick={axisStyle}
          stroke={CHART.grid}
          interval={0}
          angle={angledLabels ? -35 : 0}
          textAnchor={angledLabels ? "end" : "middle"}
          height={angledLabels ? 40 : undefined}
        />
        <YAxis
          tick={axisStyle}
          stroke={CHART.grid}
          width={56}
          tickFormatter={yTickFormatter}
          domain={yDomain}
          allowDataOverflow
        />
        <Tooltip
          {...tooltipStyle}
          cursor={{ fill: "rgba(255,255,255,0.03)" }}
          formatter={(v) =>
            valueFormatter ? valueFormatter(Number(v)) : String(v ?? "")
          }
        />
        <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={
                signedColors
                  ? d.value >= 0
                    ? CHART.up
                    : CHART.down
                  : color
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
