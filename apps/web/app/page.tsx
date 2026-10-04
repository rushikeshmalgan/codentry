import Link from "next/link";
import { getBackendHealth } from "@/lib/backend";

export const dynamic = "force-dynamic";

type HealthData = {
  status?: string;
  service?: string;
  version?: string;
  worker?: string;
};

export default async function HomePage() {
  const backend = await getBackendHealth();
  const data = (backend.data ?? {}) as HealthData;
  const operational = backend.ok;

  return (
    <main className="page">
      <div className="page-header">
        <h1>Codentry</h1>
        <p>
          An evidence-first system for analyzing GitHub pull requests: deterministic static analysis
          (ESLint + a hand-written Semgrep ruleset) that compares a PR&apos;s head against its merge
          base and reports only what the change introduces — plus a measurement harness that
          evaluates how well that analysis actually performs, with real numbers, not claims.
        </p>
      </div>

      <div className="status-row" style={{ marginBottom: 28 }}>
        <span className={`dot ${operational ? "ok" : "down"}`} />
        <strong>{operational ? "System Operational" : "Backend Unavailable"}</strong>
      </div>

      <section className="section">
        <h2>System Status</h2>
        <div className="grid cols-3">
          <div className="card">
            <div className="status-row">
              <span className="dot ok" />
              apps/web (Next.js)
            </div>
            <p className="faint" style={{ marginTop: 8 }}>Serving this page.</p>
          </div>
          <div className="card">
            <div className="status-row">
              <span className={`dot ${operational ? "ok" : "down"}`} />
              services/ai-review (FastAPI)
            </div>
            <p className="faint" style={{ marginTop: 8 }}>
              {operational
                ? `${data.service ?? "ai-review"} · v${data.version ?? "?"}`
                : "● Backend unavailable"}
            </p>
          </div>
          <div className="card">
            <div className="status-row">
              <span className={`dot ${operational && data.worker === "running" ? "ok" : operational ? "warn" : "down"}`} />
              Review worker
            </div>
            <p className="faint" style={{ marginTop: 8 }}>
              {operational ? data.worker ?? "unknown" : "● Backend unavailable"}
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Explore what&apos;s built</h2>
        <div className="grid cols-2">
          <Link href="/analysis" className="card" style={{ display: "block" }}>
            <strong>Analysis</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              Run the real ESLint + Semgrep pipeline on checked-in fixtures and inspect every finding.
            </p>
          </Link>
          <Link href="/security" className="card" style={{ display: "block" }}>
            <strong>Security &amp; Isolation</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              What protects Codentry from hostile pull-request input, and the latest verified test run.
            </p>
          </Link>
          <Link href="/evaluation" className="card" style={{ display: "block" }}>
            <strong>Evaluation &amp; Evidence</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              237 recorded test cases, real recall numbers, and a reproducible report.
            </p>
          </Link>
          <Link href="/architecture" className="card" style={{ display: "block" }}>
            <strong>Architecture</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              The implemented pipeline, what&apos;s planned next, and the line between them.
            </p>
          </Link>
        </div>
      </section>

      <section className="section">
        <h2>Final dashboard summary</h2>
        <div className="grid cols-2">
          <div className="card">
            <div className="faint" style={{ marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Currently implemented
            </div>
            <ul className="checklist done">
              <li><span className="mark">✓</span> Webhook ingestion with a durable event state machine</li>
              <li><span className="mark">✓</span> Durable, DB-backed review job queue (lease, fencing, retry)</li>
              <li><span className="mark">✓</span> Deterministic static analysis: ESLint + Semgrep</li>
              <li><span className="mark">✓</span> Differential analysis (new / existing / fixed / moved)</li>
              <li><span className="mark">✓</span> Finding identity stable under line-shift &amp; whitespace (877/877)</li>
              <li><span className="mark">✓</span> Hardened against hostile PR input (config, env, path injection)</li>
              <li><span className="mark">✓</span> Evaluation harness — 237 recorded, reproducible cases</li>
              <li><span className="mark">✓</span> GitHub App installation-token exchange (auth foundation)</li>
              <li><span className="mark">✓</span> Fail-closed production startup</li>
            </ul>
          </div>
          <div className="card">
            <div className="faint" style={{ marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Next phase
            </div>
            <ul className="checklist next">
              <li><span className="mark">○</span> AI-assisted contextual code review (Claude) — designed, not built</li>
              <li><span className="mark">○</span> Automatic PR comment posting on GitHub</li>
              <li><span className="mark">○</span> Real GitHub → Codentry end-to-end deployment</li>
              <li><span className="mark">○</span> Static + AI finding fusion</li>
              <li><span className="mark">○</span> Human-adjudicated precision measurement (needs 2 labelers)</li>
            </ul>
          </div>
        </div>
      </section>
    </main>
  );
}
