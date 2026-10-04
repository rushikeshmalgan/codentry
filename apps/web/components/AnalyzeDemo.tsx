"use client";

import { useState } from "react";
import { FindingCard, type Finding } from "./FindingCard";

type AnalyzeResult = {
  fixture: string;
  files: { filename: string; source: string }[];
  elapsed_ms: number;
  overall_status: string;
  eslint_status: string;
  semgrep_status: string;
  eslint_error: string | null;
  semgrep_error: string | null;
  finding_count: number;
  severity_counts: Record<string, number>;
  findings: Finding[];
};

const FIXTURE_OPTIONS = [
  { id: "all", label: "All three files (recommended)" },
  { id: "eslint", label: "ESLint Sample" },
  { id: "semgrep", label: "Semgrep Sample" },
  { id: "clean", label: "Clean Sample" },
];

type Phase = "idle" | "running" | "done" | "error";

function EngineStatus({ name, status, error }: { name: string; status?: string; error?: string | null }) {
  const tone = status === "completed" || status === "ok" ? "ok" : status === undefined ? "neutral" : "warn";
  return (
    <div className="card">
      <div className="status-row">
        <span className={`dot ${tone}`} />
        {name}
      </div>
      <p className="faint" style={{ marginTop: 8 }}>
        {status ? `status: ${status}` : "not run yet"}
        {error ? ` — ${error}` : ""}
      </p>
    </div>
  );
}

export function AnalyzeDemo() {
  const [fixture, setFixture] = useState("all");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  async function runAnalysis() {
    setPhase("running");
    setResult(null);
    setErrorMsg(null);
    setElapsed(0);

    const tick = setInterval(() => setElapsed((e) => e + 1), 1000);

    try {
      const res = await fetch(`/api/demo/analyze?fixture=${fixture}`);
      const body = await res.json();
      if (!res.ok) {
        setErrorMsg(body.error ?? "analysis failed");
        setPhase("error");
        return;
      }
      setResult(body);
      setPhase("done");
    } catch {
      setErrorMsg("could not reach the backend");
      setPhase("error");
    } finally {
      clearInterval(tick);
    }
  }

  return (
    <div>
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <label className="faint" htmlFor="fixture-select">Select fixture</label>
        <select
          id="fixture-select"
          className="select"
          value={fixture}
          onChange={(e) => setFixture(e.target.value)}
          disabled={phase === "running"}
        >
          {FIXTURE_OPTIONS.map((opt) => (
            <option key={opt.id} value={opt.id}>{opt.label}</option>
          ))}
        </select>
        <button className="btn primary" onClick={runAnalysis} disabled={phase === "running"}>
          {phase === "running" ? "Analyzing…" : "Run Analysis"}
        </button>
        {phase === "running" ? (
          <span className="faint" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="spinner" /> running real ESLint + Semgrep on the fixture files… {elapsed}s
          </span>
        ) : null}
      </div>

      {phase === "error" ? (
        <div className="card" style={{ marginTop: 16, borderColor: "var(--error)" }}>
          <span className="pill down">● {errorMsg}</span>
        </div>
      ) : null}

      {result ? (
        <div style={{ marginTop: 24 }}>
          <div className="grid cols-3" style={{ marginBottom: 20 }}>
            <EngineStatus name="ESLint" status={result.eslint_status} error={result.eslint_error} />
            <EngineStatus name="Semgrep" status={result.semgrep_status} error={result.semgrep_error} />
            <div className="card">
              <div className="status-row">
                <span className={`dot ${result.overall_status === "completed" ? "ok" : "warn"}`} />
                Overall
              </div>
              <p className="faint" style={{ marginTop: 8 }}>
                {result.overall_status} · {result.elapsed_ms}ms · {result.files.length} files
              </p>
            </div>
          </div>

          <div className="grid cols-4" style={{ marginBottom: 20 }}>
            <StatMini label="Files" value={result.files.length} />
            <StatMini label="Findings" value={result.finding_count} />
            <StatMini label="High+" value={(result.severity_counts.critical ?? 0) + (result.severity_counts.high ?? 0)} />
            <StatMini label="Medium/Low" value={(result.severity_counts.medium ?? 0) + (result.severity_counts.low ?? 0) + (result.severity_counts.info ?? 0)} />
          </div>

          {result.finding_count === 0 ? (
            <div className="card">
              <span className="pill ok">✓ No findings detected</span>
            </div>
          ) : (
            <div>
              {result.findings.map((f, i) => (
                <FindingCard key={i} finding={f} files={result.files} />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function StatMini({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}
