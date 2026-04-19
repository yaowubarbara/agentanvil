type Row = { scaffold: string; n: number; correct: number };
type Props = { data: Row[]; height?: number };

export default function AccuracyBarChart({ data, height = 260 }: Props) {
  if (!data.length) {
    return <div className="empty-chart">No traces yet.</div>;
  }
  const sorted = [...data].sort((a, b) => b.correct / b.n - a.correct / a.n);
  const barH = 22;
  const gap = 10;
  const labelW = 150;
  const numW = 70;
  const chartW = 720;
  const totalH = (barH + gap) * sorted.length + 20;

  return (
    <svg
      className="chart"
      width="100%"
      height={Math.max(height, totalH)}
      viewBox={`0 0 ${chartW + labelW + numW + 20} ${totalH}`}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <linearGradient id="barGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#4d6bfe" />
          <stop offset="100%" stopColor="#7b8dff" />
        </linearGradient>
        <linearGradient id="barGradPartial" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#fbbf24" />
          <stop offset="100%" stopColor="#ef4444" />
        </linearGradient>
      </defs>
      {sorted.map((row, i) => {
        const acc = row.correct / row.n;
        const y = 10 + i * (barH + gap);
        const w = chartW * acc;
        const gradId = acc >= 0.5 ? "barGrad" : "barGradPartial";
        return (
          <g key={row.scaffold}>
            <text x={labelW - 8} y={y + barH * 0.68} textAnchor="end" className="chart-label">
              {row.scaffold}
            </text>
            <rect
              x={labelW}
              y={y}
              width={chartW}
              height={barH}
              rx={3}
              className="chart-bar-bg"
            />
            <rect
              x={labelW}
              y={y}
              width={w}
              height={barH}
              rx={3}
              fill={`url(#${gradId})`}
              className="chart-bar chart-bar-animated"
              style={{
                transformOrigin: `${labelW}px ${y}px`,
              }}
            />
            <text
              x={labelW + chartW + 8}
              y={y + barH * 0.68}
              className="chart-value"
            >
              {(acc * 100).toFixed(0)}% <tspan className="chart-count">({row.correct}/{row.n})</tspan>
            </text>
          </g>
        );
      })}
    </svg>
  );
}
