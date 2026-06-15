export function Sparkline({ values }: { values: number[] }) {
  return (
    <div className="sparkline">
      {values.map((value, index) => (
        <span key={index} style={{ height: `${value}%` }} />
      ))}
    </div>
  );
}
