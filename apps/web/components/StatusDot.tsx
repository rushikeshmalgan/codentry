type Tone = "ok" | "down" | "warn" | "neutral";

export function StatusDot({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className="status-row">
      <span className={`dot ${tone}`} />
      {label}
    </span>
  );
}
