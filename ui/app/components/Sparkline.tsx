type Props = {
  values: number[]; // each 0 or 1 (or any scalar)
  width?: number;
  height?: number;
  color?: string;
};

export default function Sparkline({
  values,
  width = 60,
  height = 14,
  color = "#4d6bfe",
}: Props) {
  if (!values.length) return null;
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const path = values
    .map((v, i) => {
      const x = i * step;
      const y = height - (v / max) * height;
      return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");
  return (
    <svg width={width} height={height} className="sparkline">
      <path d={path} stroke={color} strokeWidth={1.2} fill="none" />
      {values.length > 0 && (
        <circle
          cx={(values.length - 1) * step}
          cy={height - (values[values.length - 1] / max) * height}
          r={1.8}
          fill={color}
        />
      )}
    </svg>
  );
}
