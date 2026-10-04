import { promises as fs } from "fs";
import path from "path";

export const metadata = { title: "Security — Codentry" };

type Scenario = {
  name: string;
  label: string;
  group: string;
  status: "passed" | "failed" | "skipped";
  duration_seconds: number;
  skip_reason: string | null;
};

type SecurityReport = {
  generated_at: string;
  source: string;
  counts: { total: number; passed: number; failed: number; skipped: number };
  duration_seconds: number;
  scenarios: Scenario[];
};

const PROTECTIONS = [
  {
    title: "PR-supplied analyzer config is never loaded",
    detail:
      "ESLint config is Codentry's own baseline plus, optionally, a sanitized overlay read from the trusted base commit (rules/env/globals only — never parser, plugins, extends, or a .js file).",
  },
  {
    title: "Subprocess environment is isolated",
    detail:
      "ESLint and Semgrep run with an explicit allowlisted environment, a temp HOME, and no server secret ever reaches them.",
  },
  {
    title: "PR file paths cannot become CLI flags",
    detail:
      "Paths are ./-prefixed and passed after --; absolute, drive, UNC, traversal, and control-character paths are rejected before they reach a subprocess.",
  },
  {
    title: "A PR cannot hide its own findings",
    detail:
      "Inline eslint-disable / nosemgrep comments, .eslintignore, and .semgrepignore are ignored or never written into the analysis workspace.",
  },
  {
    title: "Tool output is redacted before storage",
    detail: "Finding text and tool error snippets get best-effort secret redaction.",
  },
  {
    title: "Internal service-to-service calls require a shared secret",
    detail:
      "Vercel → Render calls carry X-Codentry-Internal-Secret, distinct from the GitHub webhook secret, and fail closed if it is unset.",
  },
  {
    title: "Internal pages are not publicly reachable",
    detail:
      "/internal/* is 404 unless explicitly enabled, then requires HTTP Basic auth; /health and /api/status reveal no configuration.",
  },
];

async function loadReport(): Promise<SecurityReport | null> {
  try {
    const file = path.join(process.cwd(), "public", "security-report.json");
    const raw = await fs.readFile(file, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function ScenarioRow({ s }: { s: Scenario }) {
  const icon = s.status === "passed" ? "✓" : s.status === "skipped" ? "○" : "✗";
  const tone = s.status === "passed" ? "ok" : s.status === "skipped" ? "neutral" : "down";
  return (
    <tr>
      <td>
        <span className={`dot ${tone}`} style={{ marginRight: 8 }} />
        {icon}
      </td>
      <td>{s.label}</td>
      <td className="faint">{s.status}{s.skip_reason ? ` — ${s.skip_reason}` : ""}</td>
      <td className="num faint">{s.duration_seconds}s</td>
    </tr>
  );
}

export default async function SecurityPage() {
  const report = await loadReport();

  return (
    <main className="page">
      <div className="page-header">
        <h1>Security &amp; Isolation</h1>
        <p>
          Codentry is designed to treat pull-request code as untrusted input. Nothing a PR supplies —
          file contents, paths, or configuration — is trusted to configure how it gets analyzed.
        </p>
      </div>

      <section className="section">
        <h2>Real protections</h2>
        <div className="grid cols-2">
          {PROTECTIONS.map((p) => (
            <div className="card" key={p.title}>
              <strong>{p.title}</strong>
              <p className="faint" style={{ marginTop: 6 }}>{p.detail}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Latest verified security test run</h2>
        <p className="lede">
          Running pytest from a browser would mean exposing arbitrary command execution, which this
          project does not do. Instead, this is the result of the last time{" "}
          <code>tests/test_security_poc.py</code> and <code>tests/test_scope_guards.py</code> were
          actually run (<code>services/ai-review/scripts/generate_security_report.py</code>).
        </p>
        {report ? (
          <>
            <div className="grid cols-4" style={{ marginBottom: 16 }}>
              <div className="stat"><div className="value">{report.counts.passed}</div><div className="label">Passed</div></div>
              <div className="stat"><div className="value">{report.counts.failed}</div><div className="label">Failed</div></div>
              <div className="stat"><div className="value">{report.counts.skipped}</div><div className="label">Skipped</div></div>
              <div className="stat"><div className="value">{report.duration_seconds}s</div><div className="label">Duration</div></div>
            </div>
            <p className="faint" style={{ marginBottom: 12 }}>
              Generated {new Date(report.generated_at).toLocaleString()} · source: {report.source}
            </p>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <table className="data">
                <thead>
                  <tr><th></th><th>Scenario</th><th>Result</th><th>Time</th></tr>
                </thead>
                <tbody>
                  {report.scenarios.map((s) => <ScenarioRow key={s.name} s={s} />)}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="card">
            <span className="pill down">● report not found — run generate_security_report.py</span>
          </div>
        )}
      </section>

      <section className="section">
        <h2>Security posture</h2>
        <div className="grid cols-2">
          <div className="card">
            <div className="status-row"><span className="dot ok" />Development</div>
            <p className="faint" style={{ marginTop: 8 }}>✓ Local fallback allowed — an in-memory store and relaxed startup checks make local development possible without any secrets.</p>
          </div>
          <div className="card">
            <div className="status-row"><span className="dot warn" />Production</div>
            <p className="faint" style={{ marginTop: 8 }}>🔒 Required secrets enforced — the service refuses to start.</p>
          </div>
        </div>
        <div className="code-block" style={{ marginTop: 14 }}>
          <div className="filename">verified: ENVIRONMENT=production, no secrets configured</div>
          <div className="code-line"><span className="src">RuntimeError: refusing to start: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required; CODENTRY_INTERNAL_WEBHOOK_SECRET is required</span></div>
        </div>
        <p className="faint" style={{ marginTop: 10 }}>
          Any environment other than development/test must supply SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
          and CODENTRY_INTERNAL_WEBHOOK_SECRET or the process exits instead of running degraded. Actual
          secret values are never displayed here or anywhere in this application.
        </p>
      </section>
    </main>
  );
}
