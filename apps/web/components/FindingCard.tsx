import { SeverityBadge, SourceBadge } from "./SeverityBadge";
import { CodeBlock } from "./CodeBlock";

export type Finding = {
  source: string;
  category: string;
  severity: string;
  confidence: number;
  title: string;
  description: string;
  file_path: string;
  start_line: number;
  end_line: number;
  suggestion?: string | null;
  reasoning?: string | null;
};

export function FindingCard({ finding, files }: { finding: Finding; files: { filename: string; source: string }[] }) {
  const file = files.find((f) => f.filename === finding.file_path || f.filename.endsWith(finding.file_path));

  return (
    <details className="finding">
      <summary>
        <SeverityBadge severity={finding.severity} />
        <SourceBadge source={finding.source} />
        <span className="title">{finding.title}</span>
        <span className="meta">{finding.file_path}:{finding.start_line}</span>
      </summary>
      <div className="body">
        <dl className="kv">
          <dt>Rule</dt>
          <dd>{finding.category}</dd>
          <dt>Severity</dt>
          <dd><SeverityBadge severity={finding.severity} /></dd>
          <dt>File</dt>
          <dd>{finding.file_path}</dd>
          <dt>Line</dt>
          <dd>{finding.start_line}{finding.end_line !== finding.start_line ? `–${finding.end_line}` : ""}</dd>
          <dt>Message</dt>
          <dd>{finding.description}</dd>
          <dt>Source</dt>
          <dd><SourceBadge source={finding.source} /></dd>
        </dl>
        {finding.suggestion ? <p className="faint">Suggestion: {finding.suggestion}</p> : null}
        {file ? (
          <CodeBlock
            filename={file.filename}
            source={file.source}
            startLine={finding.start_line}
            endLine={finding.end_line}
          />
        ) : null}
      </div>
    </details>
  );
}
