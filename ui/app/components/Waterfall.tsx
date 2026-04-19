type Event = {
  kind: string;
  step: number;
  ts: number;
};
type Props = {
  events: Event[];
  startedAt: number;
  finishedAt: number | null;
  highlightStep?: number | null;
  onSelect?: (step: number) => void;
};

const KIND_COLOR: Record<string, string> = {
  observation: "#4d6bfe",
  thought: "#7b8dff",
  tool_call: "#fbbf24",
  tool_result: "#fbbf24",
  final_answer: "#10b981",
  reward: "#ef4444",
  error: "#ef4444",
};

export default function Waterfall({
  events,
  startedAt,
  finishedAt,
  highlightStep,
  onSelect,
}: Props) {
  if (!events.length) return null;
  const tMin = startedAt;
  const tMax = (finishedAt ?? events[events.length - 1].ts) + 0.001;
  const span = Math.max(tMax - tMin, 0.001);

  const barH = 14;
  const gap = 4;
  const rowH = barH + gap;
  const chartH = rowH * events.length + 30;
  const leftLabel = 50;
  const rightPad = 12;
  const usableW = 1200 - leftLabel - rightPad;

  return (
    <div className="waterfall-wrap">
      <svg
        className="chart waterfall"
        width="100%"
        height={chartH}
        viewBox={`0 0 1200 ${chartH}`}
        preserveAspectRatio="xMinYMid meet"
      >
        {/* time axis */}
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
          const x = leftLabel + usableW * f;
          const ms = (span * f * 1000).toFixed(0);
          return (
            <g key={i}>
              <line
                x1={x}
                x2={x}
                y1={16}
                y2={chartH - 4}
                className="wf-gridline"
              />
              <text x={x} y={12} className="wf-tick">
                {ms}ms
              </text>
            </g>
          );
        })}
        {events.map((e, i) => {
          const f0 = Math.max(0, (e.ts - tMin) / span);
          const nextT =
            i + 1 < events.length ? events[i + 1].ts : tMax;
          const f1 = Math.max(f0 + 0.004, (nextT - tMin) / span);
          const x = leftLabel + usableW * f0;
          const w = Math.max(4, usableW * (f1 - f0));
          const y = 22 + i * rowH;
          const color = KIND_COLOR[e.kind] ?? "#8b96ab";
          const isHi = highlightStep === e.step;
          return (
            <g
              key={e.step}
              className={`wf-row ${isHi ? "hi" : ""}`}
              onClick={() => onSelect?.(e.step)}
              style={{ cursor: onSelect ? "pointer" : "default" }}
            >
              <text x={leftLabel - 6} y={y + barH * 0.8} textAnchor="end" className="wf-step">
                #{e.step}
              </text>
              <rect
                x={x}
                y={y}
                width={w}
                height={barH}
                rx={2}
                fill={color}
                fillOpacity={isHi ? 1 : 0.6}
                stroke={isHi ? color : "transparent"}
                strokeWidth={isHi ? 2 : 0}
              />
              <text x={x + w + 6} y={y + barH * 0.8} className="wf-kind">
                {e.kind}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
