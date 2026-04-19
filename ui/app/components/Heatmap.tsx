type Cell = { scaffold: string; task: string; correct: boolean | null };
type Props = { cells: Cell[] };

// Render an N×M heatmap of scaffold vs task_id. Green if correct, red if wrong,
// gray if not run.
export default function Heatmap({ cells }: Props) {
  if (!cells.length) return <div className="empty-chart">No runs yet to plot.</div>;

  const scaffolds = Array.from(new Set(cells.map((c) => c.scaffold)));
  const tasks = Array.from(new Set(cells.map((c) => c.task)));
  const lookup = new Map<string, Cell>();
  for (const c of cells) lookup.set(`${c.scaffold}::${c.task}`, c);

  const cellSize = 22;
  const scaffoldLabelW = 160;
  const taskLabelH = 110;
  const w = scaffoldLabelW + tasks.length * (cellSize + 2);
  const h = taskLabelH + scaffolds.length * (cellSize + 2);

  return (
    <svg
      className="chart heatmap"
      width="100%"
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Task labels rotated */}
      {tasks.map((task, i) => (
        <text
          key={task}
          x={scaffoldLabelW + i * (cellSize + 2) + cellSize / 2}
          y={taskLabelH - 10}
          textAnchor="end"
          transform={`rotate(-55 ${
            scaffoldLabelW + i * (cellSize + 2) + cellSize / 2
          } ${taskLabelH - 10})`}
          className="chart-label small"
        >
          {task.length > 22 ? "…" + task.slice(-22) : task}
        </text>
      ))}
      {/* Scaffold labels + cells */}
      {scaffolds.map((sc, rowIdx) => (
        <g key={sc}>
          <text
            x={scaffoldLabelW - 8}
            y={taskLabelH + rowIdx * (cellSize + 2) + cellSize * 0.7}
            textAnchor="end"
            className="chart-label"
          >
            {sc}
          </text>
          {tasks.map((task, colIdx) => {
            const c = lookup.get(`${sc}::${task}`);
            const x = scaffoldLabelW + colIdx * (cellSize + 2);
            const y = taskLabelH + rowIdx * (cellSize + 2);
            const cls =
              c == null
                ? "hm-empty"
                : c.correct === true
                ? "hm-ok"
                : c.correct === false
                ? "hm-bad"
                : "hm-unknown";
            const title =
              c == null
                ? `${sc} × ${task}: no run`
                : `${sc} × ${task}: ${c.correct ? "✓" : "✗"}`;
            return (
              <g key={task + colIdx}>
                <title>{title}</title>
                <rect
                  x={x}
                  y={y}
                  width={cellSize}
                  height={cellSize}
                  rx={3}
                  className={`hm-cell ${cls}`}
                />
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}
