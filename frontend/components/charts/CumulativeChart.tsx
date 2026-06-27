"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART, axisStyle, tooltipStyle } from "./chartTheme";
import { usd, utc } from "@/lib/format";

export interface CumPoint {
  xEpoch: number;
  pnl: number;
}

/** Cumulative PnL over time as a filled area with a zero reference line. */
export function CumulativeChart({
  data,
  height = 240,
}: {
  data: CumPoint[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <defs>
          <linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART.accent} stopOpacity={0.35} />
            <stop offset="100%" stopColor={CHART.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={CHART.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="xEpoch"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => utc(new Date(v).toISOString()).slice(5, 10)}
          tick={axisStyle}
          stroke={CHART.grid}
          minTickGap={40}
        />
        <YAxis
          tick={axisStyle}
          stroke={CHART.grid}
          width={64}
          tickFormatter={(v) => usd(v, 0)}
        />
        <Tooltip
          {...tooltipStyle}
          labelFormatter={(v) => utc(new Date(Number(v)).toISOString())}
          formatter={(v) => [usd(Number(v)), "Cumulative PnL"]}
        />
        <ReferenceLine y={0} stroke={CHART.muted} strokeDasharray="3 3" />
        <Area
          type="monotone"
          dataKey="pnl"
          stroke={CHART.accent}
          strokeWidth={1.8}
          fill="url(#pnlFill)"
          isAnimationActive={false}
          connectNulls
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
