export function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info ak-panel">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
