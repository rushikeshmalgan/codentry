const KNOWN = new Set(["critical", "high", "medium", "low", "info"]);

export function SeverityBadge({ severity }: { severity: string }) {
  const sev = KNOWN.has(severity) ? severity : "info";
  return <span className={`badge sev-${sev}`}>{severity}</span>;
}

export function SourceBadge({ source }: { source: string }) {
  return <span className="badge source">{source}</span>;
}
