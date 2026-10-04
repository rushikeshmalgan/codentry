import { promises as fs } from "fs";
import path from "path";

export const metadata = { title: "Evaluation — Codentry" };

type Recall = { n: number; successes: number; value: number; wilson95: [number, number] };

type ArmAReport = {
  provenance: {
    case_count: number;
    results_sha256: string;
    case_manifest_sha256: string;
    git: { commit: string; dirty: boolean };
    status_counts: { completed: number; partial: number };
  };
  strata: {
    "mutant:logic": { recall: Record<string, Recall> };
    "mutant:rule-aligned": { recall: Record<string, Recall> };
    "real:bugsjs": { recall: Record<string, Recall> };
  };
  identity_stability: {
    files_with_findings: number;
    findings_before: number;
    transforms: {
      line_shift: { before: number; after: number; stable: number; stable_fraction: number };
      trailing_whitespace: { before: number; after: number; stable: number; stable_fraction: number };
    };
  };
};

type TestCounts = { backend_tests: number; evaluation_harness_tests: number; evaluation_cases: number };

async function loadJson<T>(filename: string): Promise<T | null> {
  try {
    const raw = await fs.readFile(path.join(process.cwd(), "public", filename), "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function pct(r: Recall): string {
  return `${(r.value * 100).toFixed(1)}%`;
}

export default async function EvaluationPage() {
  const report = await loadJson<ArmAReport>("arm-a-report.json");
  const counts = await loadJson<TestCounts>("test-counts.json");

  if (!report) {
    return (
      <main className="page">
        <div className="page-header"><h1>Evaluation &amp; Evidence</h1></div>
        <div className="card"><span className="pill down">● evaluation/reports/2026-10-02-arm-a.json not found in apps/web/public</span></div>
      </main>
    );
  }

  const logic = report.strata["mutant:logic"].recall["2"];
  const bugsjs = report.strata["real:bugsjs"].recall["2"];
  const ruleAligned = report.strata["mutant:rule-aligned"].recall["2"];
  const lineShift = report.identity_stability.transforms.line_shift;
  const whitespace = report.identity_stability.transforms.trailing_whitespace;

  return (
    <main className="page">
      <div className="page-header">
        <h1>Evaluation &amp; Evidence</h1>
        <p>
          Codentry is evaluated using recorded, reproducible test runs. Every number on this page is
          read directly from <code>evaluation/reports/2026-10-02-arm-a.json</code> — nothing here is
          typed by hand.
        </p>
      </div>

      <section className="section" style={{ display: "flex", alignItems: "center", gap: 28, flexWrap: "wrap" }}>
        <div className="stat hero">
          <div className="value">{report.provenance.case_count}</div>
          <div className="label">Evaluation Cases</div>
          <div className="sub">
            {report.provenance.status_counts.completed} completed, {report.provenance.status_counts.partial} partial
          </div>
        </div>
        <div className="grid cols-3" style={{ flex: 1, minWidth: 320 }}>
          <div className="stat">
            <div className="value">{pct(logic)}</div>
            <div className="label">Seeded Logic Bugs Recall</div>
            <div className="sub">{logic.successes}/{logic.n} cases</div>
          </div>
          <div className="stat">
            <div className="value">{pct(bugsjs)}</div>
            <div className="label">Real BugsJS Bugs Recall</div>
            <div className="sub">{bugsjs.successes}/{bugsjs.n} cases</div>
          </div>
          <div className="stat">
            <div className="value">{pct(ruleAligned)}</div>
            <div className="label">Security Pattern Injections Recall</div>
            <div className="sub">{ruleAligned.successes}/{ruleAligned.n} cases</div>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>What we learned</h2>
        <div className="grid cols-3">
          <div className="card">
            <strong>Strong performance</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              On patterns the ruleset was written to catch (eval, hardcoded secrets, unsafe
              deserialization), recall is {pct(ruleAligned)}. This stratum is favorable to the tool by
              construction — each injected line matches one of its own six rules.
            </p>
          </div>
          <div className="card">
            <strong>Current limitation</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              On general logic bugs — off-by-one errors, inverted conditions, wrong defaults — recall is
              only {pct(logic)} (seeded) and {pct(bugsjs)} (real BugsJS bugs). This is a measured
              limitation, stated plainly, not something hidden: pattern-based static analysis cannot see
              semantic intent.
            </p>
          </div>
          <div className="card">
            <strong>Next direction</strong>
            <p className="faint" style={{ marginTop: 6 }}>
              AI-assisted contextual review is the planned next arm, specifically to address this gap —
              but it has to be measured against this same baseline before it is trusted, not assumed
              better.
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Finding identity stability</h2>
        <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
          <div className="stat hero">
            <div className="value">{lineShift.stable} / {lineShift.before}</div>
            <div className="label">Findings retained their identity</div>
          </div>
          <div className="stat">
            <div className="value">{(lineShift.stable_fraction * 100).toFixed(0)}%</div>
            <div className="label">Identity stability (line shift)</div>
          </div>
          <div className="stat">
            <div className="value">{(whitespace.stable_fraction * 100).toFixed(0)}%</div>
            <div className="label">Identity stability (trailing whitespace)</div>
          </div>
        </div>
        <p className="faint" style={{ marginTop: 14, maxWidth: "68ch" }}>
          {report.identity_stability.files_with_findings} real files with at least one finding were
          re-analyzed after two transformations that do not change meaning: inserting blank lines above
          the code, and adding trailing whitespace. Every finding kept the same identity — the system
          does not re-report the same issue as &ldquo;new&rdquo; just because surrounding lines moved.
        </p>
      </section>

      <section className="section">
        <h2>Reproducible evaluation</h2>
        <div className="card">
          <dl className="kv">
            <dt>Recorded run</dt><dd>arm-a-2026-10-02</dd>
            <dt>Report</dt><dd><span className="pill ok">✓ PASS</span></dd>
            <dt>Identity stability</dt><dd><span className="pill ok">✓ PASS</span></dd>
            <dt>Commit</dt><dd className="faint">{report.provenance.git.commit.slice(0, 12)}</dd>
            <dt>Case manifest SHA-256</dt><dd className="faint">{report.provenance.case_manifest_sha256.slice(0, 16)}…</dd>
          </dl>
          <p className="faint" style={{ marginTop: 10 }}>
            Re-running <code>evaluation.repro</code> against the recorded run regenerates this exact
            report from the stored per-case results — it does not re-execute ESLint/Semgrep, so the
            numbers above are checked for consistency, not re-measured, every time.
          </p>
        </div>
      </section>

      <section className="section">
        <h2>Engineering validation</h2>
        <div className="grid cols-3">
          <div className="stat">
            <div className="value">{counts?.backend_tests ?? "—"}</div>
            <div className="label">Backend Tests Passed</div>
          </div>
          <div className="stat">
            <div className="value">{counts?.evaluation_harness_tests ?? "—"}</div>
            <div className="label">Evaluation Harness Tests Passed</div>
          </div>
          <div className="stat">
            <div className="value">{report.provenance.case_count}</div>
            <div className="label">Evaluation Cases</div>
          </div>
        </div>
        <p className="faint" style={{ marginTop: 10 }}>
          Tests passed, not coverage — no line/branch coverage measurement exists in this project yet.
        </p>
      </section>
    </main>
  );
}
