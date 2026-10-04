export const metadata = { title: "Architecture — Codentry" };

export default function ArchitecturePage() {
  return (
    <main className="page">
      <div className="page-header">
        <h1>Architecture</h1>
        <p>
          What is actually implemented today, separated clearly from what is planned. See{" "}
          <code>docs/architecture.md</code> for the full write-up this page summarizes.
        </p>
      </div>

      <section className="section">
        <h2>Implemented pipeline</h2>
        <div className="flow">
{`Pull Request
   │
   ▼
`}<span className="implemented">{`Webhook Layer`}</span>{`         `}<span className="implemented">implemented</span>{`
   (HMAC verify, event allowlist, forwarded to the backend)
   │
   ▼
`}<span className="implemented">{`Job Queue`}</span>{`               `}<span className="implemented">implemented</span>{`
   (durable, DB-backed review_runs; lease + fencing + retry)
   │
   ▼
`}<span className="implemented">{`Analysis Worker`}</span>{`          `}<span className="implemented">implemented</span>{`
   (one in-process worker, polls the queue)
   │
   ├──▶ `}<span className="implemented">ESLint</span>{`
   └──▶ `}<span className="implemented">Semgrep</span>{`
   │
   ▼
`}<span className="implemented">{`Finding Pipeline`}</span>{`         `}<span className="implemented">implemented</span>{`
   (differential base→head, stable identity, new/existing/fixed/moved)
   │
   ▼
`}<span className="implemented">{`Evaluation Layer`}</span>{`         `}<span className="implemented">implemented</span>{`
   (237 recorded cases, reproducible reports)
`}
        </div>
      </section>

      <section className="section">
        <h2>GitHub integration</h2>
        <table className="data">
          <thead><tr><th>Capability</th><th>Status</th></tr></thead>
          <tbody>
            <tr><td>GitHub App groundwork</td><td><span className="pill ok">✓ Present</span></td></tr>
            <tr><td>Authentication foundation (installation token exchange)</td><td><span className="pill ok">✓ Implemented / tested</span></td></tr>
            <tr><td>Real PR → Codentry end-to-end run</td><td><span className="pill">○ Not yet deployed</span></td></tr>
            <tr><td>Automatic PR comments</td><td><span className="pill">○ Not yet implemented</span></td></tr>
          </tbody>
        </table>
        <p className="faint" style={{ marginTop: 10 }}>
          No GitHub App, Supabase project, Render service, or Vercel deployment exists for this project
          yet. Verification so far is a local run with a mocked GitHub HTTP layer and the real ESLint +
          Semgrep tools — not real GitHub end-to-end.
        </p>
      </section>

      <section className="section">
        <h2>Next phase — not implemented</h2>
        <div className="flow">
{`PR Diff + Static Findings
   │
   ▼
`}<span className="planned">{`AI Contextual Review`}</span>{`     `}<span className="planned">planned</span>{`
   │
   ▼
`}<span className="planned">{`Structured Findings`}</span>{`      `}<span className="planned">planned</span>{`
   │
   ▼
`}<span className="planned">{`Validation + Dedup`}</span>{`       `}<span className="planned">planned</span>{`
   │
   ▼
`}<span className="planned">{`Final Review`}</span>{`             `}<span className="planned">planned</span>{`
`}
        </div>
        <p className="faint" style={{ marginTop: 10 }}>
          Current status: not implemented yet. A design and cost estimate exists
          (<code>docs/AI_ARM_DESIGN_AND_COST.md</code>), deliberately deferred until the static-analysis
          baseline was measured and a labeling process existed to judge it honestly.
        </p>
      </section>
    </main>
  );
}
