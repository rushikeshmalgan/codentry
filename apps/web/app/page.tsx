import { getBackendHealth } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const backend = await getBackendHealth();

  return (
    <main>
      <h1>Codentry</h1>
      <p>
        Evidence-first GitHub pull-request analysis: differential static analysis (ESLint and a
        small Semgrep ruleset) that reports what a change introduces. Foundation-hardening phase —
        there is no AI reviewer yet.
      </p>

      <h2>Service status</h2>
      <div className="status-row">
        <span className="dot ok" />
        apps/web: ok
      </div>
      <div className="status-row">
        <span className={`dot ${backend.ok ? "ok" : "down"}`} />
        services/ai-review: {backend.ok ? "ok" : "unreachable"}
      </div>

      <p>
        This page only proves the frontend can reach the backend. Comments are not posted to pull
        requests yet. See <code>docs/architecture.md</code> for what exists and what does not.
      </p>
    </main>
  );
}
