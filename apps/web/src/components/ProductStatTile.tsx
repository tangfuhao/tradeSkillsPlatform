export default function ProductStatTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="neon-stat-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}
