"use client";

import { useState } from "react";
import { FindingCard, type Finding } from "./FindingCard";
import type { AiFinding } from "@/lib/ai-review";

type AiReviewResult = {
  findings: AiFinding[];
  discarded_count: number;
  error: string | null;
  model: string;
  elapsed_ms: number;
};

type Phase = "idle" | "running" | "done" | "error";

// Shapes a verified AI finding like a static one so the same FindingCard renders it.
function toCardFinding(f: AiFinding): Finding {
  return {
    source: "AI",
    category: "AI review (quote verified)",
    severity: f.severity,
    title: f.title,
    description: f.explanation,
    file_path: f.file,
    start_line: f.start_line,
    end_line: f.end_line,
  };
}

// The AI arm (experimental): runs only when clicked, after the static results
// are on screen, and keeps its own findings and counts apart from them.
export function AiReviewPanel({ fixture, files }: { fixture: string; files: { filename: string; source: string }[] }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<AiReviewResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  async function runReview() {
    setPhase("running");
    setResult(null);
    setErrorMsg(null);
    setElapsed(0);

    const tick = setInterval(() => setElapsed((e) => e + 1), 1000);

    try {
      const res = await fetch(`/api/demo/ai-review?fixture=${fixture}`);
      const body = await res.json();
      if (!res.ok) {
        setErrorMsg(body.error ?? "AI review failed");
        setPhase("error");
        return;
      }
      setResult(body);
      setPhase("done");
    } catch {
      setErrorMsg("could not reach the AI review route");
      setPhase("error");
    } finally {
      clearInterval(tick);
    }
  }

  return (
    <section className="section">
      <h2>AI arm (experimental)</h2>
      <p className="lede">
        A local model (through Ollama) reviews the same files. A finding is kept only if the code it
        quotes appears verbatim in the file. These results are separate from the static results above;
        the counts are never combined.
      </p>

      <div className="card" style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <button className="btn primary" onClick={runReview} disabled={phase === "running"}>
          {phase === "running" ? "Reviewing…" : "Run AI Review (local Qwen2.5-Coder)"}
        </button>
        {phase === "running" ? (
          <span className="faint" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="spinner" /> waiting for the local model… {elapsed}s (often 30–90s)
          </span>
        ) : null}
      </div>

      {phase === "error" ? (
        <div className="card" style={{ marginTop: 16, borderColor: "var(--error)" }}>
          <span className="pill down">● {errorMsg}</span>
        </div>
      ) : null}

      {result ? (
        <div style={{ marginTop: 16 }}>
          <div className="card" style={{ marginBottom: 16 }}>
            <p className="faint">
              model: {result.model} · {(result.elapsed_ms / 1000).toFixed(1)}s ·{" "}
              {result.findings.length} verified AI findings · {result.discarded_count} findings discarded
              (quote didn&apos;t match code)
            </p>
            {result.error ? (
              <span className="pill down" style={{ marginTop: 8 }}>● {result.error}</span>
            ) : null}
          </div>

          {result.findings.length === 0 ? (
            <div className="card">
              <span className="pill">No verified AI findings</span>
            </div>
          ) : (
            <div>
              {result.findings.map((f, i) => (
                <FindingCard key={i} finding={toCardFinding(f)} files={files} />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
