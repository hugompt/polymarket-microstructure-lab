// Shared Recharts styling constants for the dark data UI.
export const CHART = {
  grid: "#242a36",
  axis: "#8b94a7",
  tooltipBg: "#171b24",
  tooltipBorder: "#242a36",
  up: "#34d399",
  down: "#f87171",
  accent: "#4f9eff",
  amber: "#fbbf24",
  violet: "#a78bfa",
  cyan: "#22d3ee",
  muted: "#8b94a7",
};

export const SERIES_PALETTE = [
  CHART.accent,
  CHART.amber,
  CHART.violet,
  CHART.cyan,
  CHART.up,
  CHART.down,
];

export const axisStyle = { fontSize: 11, fill: CHART.axis } as const;

export const tooltipStyle = {
  contentStyle: {
    background: CHART.tooltipBg,
    border: `1px solid ${CHART.tooltipBorder}`,
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: CHART.muted, fontSize: 11 },
  itemStyle: { color: "#e6e9ef" },
} as const;
