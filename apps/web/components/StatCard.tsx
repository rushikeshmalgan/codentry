export function StatCard({
  value,
  label,
  sub,
  hero,
}: {
  value: string;
  label: string;
  sub?: string;
  hero?: boolean;
}) {
  return (
    <div className={`stat ${hero ? "hero" : ""}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  );
}
