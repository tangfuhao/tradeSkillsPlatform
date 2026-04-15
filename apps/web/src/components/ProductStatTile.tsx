export default function ProductStatTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}
