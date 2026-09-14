import { getBackendHealth } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const backend = await getBackendHealth();

  return (
    <main>
      <h1>Codentry</h1>
      <p>AI-powered GitHub code review assistant — Phase 1 foundation.</p>

      <h2>Service status</h2>
      <div className="status-row">
        <span className="dot ok" />
        apps/web: ok
      </div>
      <div className="status-row">
        <span className={`dot ${backend.ok ? "ok" : "down"}`} />
        services/ai-review: {backend.ok ? "ok" : `unreachable (${backend.error})`}
      </div>

      <p>
        No GitHub review functionality exists yet — this page only proves the
        frontend can reach the backend. See <code>docs/</code> for the full
        roadmap.
      </p>
    </main>
  );
}
