import { AnalyzeDemo } from "@/components/AnalyzeDemo";

export const metadata = { title: "Analysis — Codentry" };

export default function AnalysisPage() {
  return (
    <main className="page">
      <div className="page-header">
        <h1>Analyze Code</h1>
        <p>
          Runs the real analysis engine (<code>analysis/static_analysis.py</code>) against the
          checked-in fixtures below — the same ESLint and Semgrep pipeline the review worker uses on
          real pull requests. No analysis logic is duplicated in the frontend; this page only calls
          the engine and renders its real output.
        </p>
      </div>
      <AnalyzeDemo />
    </main>
  );
}
