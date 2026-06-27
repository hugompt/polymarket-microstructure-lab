"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART, axisStyle, tooltipStyle } from "./chartTheme";
import { utcTime } from "@/lib/format";

export interface LineDef {
  /** data key on each point */
  dataKey: string;
  name: string;
  color: string;
  /** y-axis id when using a secondary axis */
  yAxisId?: string;
  dot?: boolean;
}

export interface TradeMarker {
  /** x value (epoch ms) where the marker sits */
  x: number;
  /** y value (price 0..1) */
  y: number;
  side: string;
  outcome: string;
  size: number | null;
}

/**
 * Multi-line time series. `data` rows must include an `xEpoch` (ms) numeric
 * field used for the X axis so markers align. Optional `markers` overlay
 * target-wallet trades as reference dots.
 */
export function TimeSeriesChart({
  data,
  lines,
  height = 240,
  yDomain,
  yTickFormatter,
  markers,
  rightLines,
  rightYDomain,
  rightYTickFormatter,
}: {
  data: Array<Record<string, number | null>>;
  lines: LineDef[];
  height?: number;
  yDomain?: [number | "auto", number | "auto"];
  yTickFormatter?: (v: number) => string;
  markers?: TradeMarker[];
  rightLines?: LineDef[];
  rightYDomain?: [number | "auto", number | "auto"];
  rightYTickFormatter?: (v: number) => string;
}) {
  const hasRight = (rightLines?.length ?? 0) > 0;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: hasRight ? 8 : 16, left: 0, bottom: 4 }}>
        <CartesianGrid stroke={CHART.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="xEpoch"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => utcTime(new Date(v).toISOString())}
          tick={axisStyle}
          stroke={CHART.grid}
          minTickGap={40}
        />
        <YAxis
          yAxisId="left"
          domain={yDomain ?? ["auto", "auto"]}
          tick={axisStyle}
          stroke={CHART.grid}
          tickFormatter={yTickFormatter}
          width={52}
        />
        {hasRight && (
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={rightYDomain ?? ["auto", "auto"]}
            tick={axisStyle}
            stroke={CHART.grid}
            tickFormatter={rightYTickFormatter}
            width={64}
          />
        )}
        <Tooltip
          {...tooltipStyle}
          labelFormatter={(v) => `${utcTime(new Date(Number(v)).toISOString())} UTC`}
        />
        {lines.map((l) => (
          <Line
            key={l.dataKey}
            yAxisId={l.yAxisId ?? "left"}
            type="monotone"
            dataKey={l.dataKey}
            name={l.name}
            stroke={l.color}
            dot={l.dot ?? false}
            strokeWidth={1.6}
            isAnimationActive={false}
            connectNulls
          />
        ))}
        {rightLines?.map((l) => (
          <Line
            key={l.dataKey}
            yAxisId="right"
            type="monotone"
            dataKey={l.dataKey}
            name={l.name}
            stroke={l.color}
            dot={false}
            strokeWidth={1.6}
            isAnimationActive={false}
            connectNulls
          />
        ))}
        {markers?.map((m, i) => (
          <ReferenceDot
            key={i}
            yAxisId="left"
            x={m.x}
            y={m.y}
            r={4}
            fill={m.side?.toUpperCase() === "BUY" ? CHART.up : CHART.down}
            stroke="#0a0c10"
            strokeWidth={1}
            ifOverflow="extendDomain"
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/**
 * Standalone scatter used where a pure marker plot is wanted (kept minimal).
 * Currently unused by pages but exported for reuse.
 */
export function MarkerScatter({
  markers,
  height = 120,
}: {
  markers: TradeMarker[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid stroke={CHART.grid} strokeDasharray="2 4" />
        <XAxis
          dataKey="x"
          type="number"
          domain={["dataMin", "dataMax"]}
          tick={axisStyle}
          stroke={CHART.grid}
          tickFormatter={(v) => utcTime(new Date(v).toISOString())}
        />
        <YAxis dataKey="y" type="number" tick={axisStyle} stroke={CHART.grid} />
        <Tooltip {...tooltipStyle} />
        <Scatter data={markers} fill={CHART.accent} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}
