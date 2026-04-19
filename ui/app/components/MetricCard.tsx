type Props = {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
  trend?: number; // -1..+1 ish
};

export default function MetricCard({ label, value, sub, accent = "#7cc4ff", trend }: Props) {
  return (
    <div
      className="metric-card"
      style={{ ["--metric-accent" as string]: accent }}
    >
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
      {typeof trend === "number" && (
        <div className={`metric-trend ${trend >= 0 ? "up" : "down"}`}>
          {trend >= 0 ? "▲" : "▼"} {Math.abs(trend * 100).toFixed(1)}%
        </div>
      )}
    </div>
  );
}
