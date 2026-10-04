export function CodeBlock({
  filename,
  source,
  startLine,
  endLine,
  context = 4,
}: {
  filename: string;
  source: string;
  startLine?: number;
  endLine?: number;
  context?: number;
}) {
  const lines = source.split("\n");
  const total = lines.length;
  const from = startLine ? Math.max(1, startLine - context) : 1;
  const to = endLine ? Math.min(total, endLine + context) : total;
  const flaggedFrom = startLine ?? -1;
  const flaggedTo = endLine ?? startLine ?? -1;

  const visible = lines.slice(from - 1, to);

  return (
    <div className="code-block">
      <div className="filename">{filename}</div>
      <div>
        {visible.map((line, i) => {
          const lineNo = from + i;
          const flagged = lineNo >= flaggedFrom && lineNo <= flaggedTo;
          return (
            <div key={lineNo} className={`code-line ${flagged ? "flagged" : ""}`}>
              <span className="ln">{lineNo}</span>
              <span className="src">{line || " "}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
