"use strict";
/*
 * Mutation-site finder and parse checker for the evaluation harness.
 *
 * Reads ONE JSON document on stdin, writes ONE JSON document on stdout.
 *
 *   {"command": "enumerate", "items": [{"name", "filename", "text"}]}
 *       -> {"typescript": "<version>", "results": [{"name", "sites": [...], "points": [...]}]}
 *   {"command": "check", "items": [{"name", "filename", "text"}]}
 *       -> {"typescript": "<version>", "results": [{"name", "ok": bool, "errors": [...]}]}
 *
 * It only *reads* and *parses* source text (never executes it) and makes no
 * random choices: sites are listed in source order, and choosing among them is
 * done by the seeded RNG in mutate.py. The parser is the `typescript` package
 * pinned by services/ai-review/analysis/eslint-baseline/package-lock.json.
 *
 * Eight logic operators (one site = one single-line edit, so the changed line
 * range is exact):
 *   relational-flip   <  <->  <=      >  <->  >=
 *   equality-flip     ==  <->  !=     === <->  !==
 *   logical-swap      &&  <->  ||
 *   negate-condition  if/while/for/?: condition  C  ->  !(C)   (or  !C -> C)
 *   drop-guard        delete a whole `if (..) return/throw/continue/break` guard
 *   remove-await      await x  ->  x
 *   off-by-one        a[i] -> a[i + 1]     x.length (in a comparison) -> x.length - 1
 *   constant-change   integer literal N  ->  N + 1
 * `points` are statement positions inside function bodies, used to insert the
 * separately-reported rule-aligned injections.
 */
const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");

const baseline = path.resolve(
  __dirname, "..", "..", "services", "ai-review", "analysis", "eslint-baseline"
);
const ts = createRequire(path.join(baseline, "package.json"))("typescript");

const K = ts.SyntaxKind;

const RELATIONAL = new Map([
  [K.LessThanToken, "<="],
  [K.LessThanEqualsToken, "<"],
  [K.GreaterThanToken, ">="],
  [K.GreaterThanEqualsToken, ">"],
]);
const EQUALITY = new Map([
  [K.EqualsEqualsToken, "!="],
  [K.ExclamationEqualsToken, "=="],
  [K.EqualsEqualsEqualsToken, "!=="],
  [K.ExclamationEqualsEqualsToken, "==="],
]);
const LOGICAL = new Map([
  [K.AmpersandAmpersandToken, "||"],
  [K.BarBarToken, "&&"],
]);
const COMPARISONS = new Set([...RELATIONAL.keys(), ...EQUALITY.keys()]);

function scriptKind(filename) {
  return filename.endsWith(".ts") ? ts.ScriptKind.TS : ts.ScriptKind.JS;
}

function parse(filename, text) {
  return ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true, scriptKind(filename));
}

function inTypePosition(node) {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isTypeNode(p)) return true;
    if (ts.isStatement(p)) return false;
  }
  return false;
}

function enumerate(filename, text) {
  const sf = parse(filename, text);
  const line = (pos) => sf.getLineAndCharacterOfPosition(pos).line + 1;
  const sites = [];
  const points = [];

  function add(operator, start, end, replacement, detail) {
    if (line(start) !== line(end)) return; // single-line edits only: exact line range
    if (text.slice(start, end) === replacement) return;
    sites.push({
      operator, start, end, replacement, line: line(start), before: text.slice(start, end), detail,
    });
  }

  function isGuard(node) {
    if (!ts.isIfStatement(node) || node.elseStatement) return false;
    const exits = (s) =>
      ts.isReturnStatement(s) || ts.isThrowStatement(s) ||
      ts.isContinueStatement(s) || ts.isBreakStatement(s);
    const then = node.thenStatement;
    const exitsEarly = exits(then) || (ts.isBlock(then) && then.statements.length === 1 && exits(then.statements[0]));
    if (!exitsEarly) return false;
    const parent = node.parent;
    return ts.isBlock(parent) || ts.isSourceFile(parent) || ts.isCaseClause(parent) || ts.isDefaultClause(parent);
  }

  function visit(node) {
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken;
      const s = op.getStart(sf);
      const e = op.getEnd();
      if (RELATIONAL.has(op.kind)) add("relational-flip", s, e, RELATIONAL.get(op.kind), `${text.slice(s, e)} -> ${RELATIONAL.get(op.kind)}`);
      if (EQUALITY.has(op.kind)) add("equality-flip", s, e, EQUALITY.get(op.kind), `${text.slice(s, e)} -> ${EQUALITY.get(op.kind)}`);
      if (LOGICAL.has(op.kind)) add("logical-swap", s, e, LOGICAL.get(op.kind), `${text.slice(s, e)} -> ${LOGICAL.get(op.kind)}`);
      // `.length` compared with something: shift the bound by one
      if (RELATIONAL.has(op.kind) || COMPARISONS.has(op.kind)) {
        for (const side of [node.left, node.right]) {
          if (ts.isPropertyAccessExpression(side) && side.name.text === "length") {
            add("off-by-one", side.getStart(sf), side.getEnd(), `${side.getText(sf)} - 1`, "length -> length - 1");
          }
        }
      }
    }

    const cond =
      (ts.isIfStatement(node) || ts.isWhileStatement(node) || ts.isDoStatement(node)) ? node.expression :
      ts.isConditionalExpression(node) ? node.condition :
      ts.isForStatement(node) ? node.condition : null;
    if (cond) {
      const s = cond.getStart(sf);
      const e = cond.getEnd();
      if (ts.isPrefixUnaryExpression(cond) && cond.operator === K.ExclamationToken) {
        add("negate-condition", s, e, cond.operand.getText(sf), "!C -> C");
      } else {
        add("negate-condition", s, e, `!(${text.slice(s, e)})`, "C -> !(C)");
      }
    }

    if (isGuard(node)) {
      const startLine = line(node.getStart(sf));
      const endLine = line(node.getEnd());
      const lines = text.split("\n");
      const first = lines[startLine - 1];
      const last = lines[endLine - 1];
      const before = first.slice(0, sf.getLineAndCharacterOfPosition(node.getStart(sf)).character);
      const after = last.slice(sf.getLineAndCharacterOfPosition(node.getEnd()).character);
      if (/^\s*$/.test(before) && /^\s*\r?$/.test(after)) {
        let start = 0;
        for (let i = 0; i < startLine - 1; i++) start += lines[i].length + 1;
        let end = start;
        for (let i = startLine - 1; i < endLine; i++) end += lines[i].length + 1;
        // whole-line deletion: recorded on the last line's terminator too
        sites.push({
          operator: "drop-guard", start, end: Math.min(end, text.length), replacement: "",
          line: startLine, endLine, before: text.slice(start, Math.min(end, text.length)),
          detail: "guard removed",
        });
      }
    }

    if (ts.isAwaitExpression(node)) {
      const s = node.getStart(sf);
      const e = node.expression.getStart(sf);
      add("remove-await", s, e, "", "await removed");
    }

    if (ts.isElementAccessExpression(node) && ts.isIdentifier(node.argumentExpression)) {
      const arg = node.argumentExpression;
      add("off-by-one", arg.getStart(sf), arg.getEnd(), `${arg.getText(sf)} + 1`, "index -> index + 1");
    }

    // Judge the literal as written (node.text is normalized: 0xff -> "255", 1e3 -> "1000").
    // Only plain decimal integers, so the edit is a readable N -> N + 1.
    if (ts.isNumericLiteral(node) && !inTypePosition(node)) {
      const written = text.slice(node.getStart(sf), node.getEnd());
      const p = node.parent;
      const isKey = (ts.isPropertyAssignment(p) && p.name === node) || ts.isEnumMember(p);
      if (/^(0|[1-9][0-9]*)$/.test(written) && !isKey) {
        add("constant-change", node.getStart(sf), node.getEnd(), String(Number(written) + 1), `${written} -> ${Number(written) + 1}`);
      }
    }

    // insertion points for rule-aligned injections: a statement that starts its own line in a function body
    if (
      ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) ||
      ts.isArrowFunction(node) || ts.isMethodDeclaration(node)
    ) {
      const body = node.body;
      const param = node.parameters.find((p) => ts.isIdentifier(p.name));
      if (body && ts.isBlock(body) && param) {
        for (const stmt of body.statements) {
          const sPos = stmt.getStart(sf);
          const lc = sf.getLineAndCharacterOfPosition(sPos);
          const lines = text.split("\n");
          const prefix = lines[lc.line].slice(0, lc.character);
          const isDirective = ts.isExpressionStatement(stmt) && ts.isStringLiteral(stmt.expression);
          const isSuper = ts.isExpressionStatement(stmt) && ts.isCallExpression(stmt.expression) && stmt.expression.expression.kind === K.SuperKeyword;
          if (!/^\s*$/.test(prefix) || isDirective || isSuper) continue;
          let offset = 0;
          for (let i = 0; i < lc.line; i++) offset += lines[i].length + 1;
          points.push({ offset, line: lc.line + 1, indent: prefix, param: param.name.text });
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);

  sites.sort((a, b) => a.start - b.start || (a.operator < b.operator ? -1 : a.operator > b.operator ? 1 : 0));
  return { sites, points };
}

function check(filename, text) {
  const out = ts.transpileModule(text, {
    fileName: filename,
    reportDiagnostics: true,
    compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext, allowJs: true },
  });
  const errors = (out.diagnostics || [])
    .filter((d) => d.category === ts.DiagnosticCategory.Error)
    .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
  return { ok: errors.length === 0, errors };
}

const request = JSON.parse(fs.readFileSync(0, "utf8"));
const results = request.items.map((item) => {
  if (request.command === "enumerate") return { name: item.name, ...enumerate(item.filename, item.text) };
  if (request.command === "check") return { name: item.name, ...check(item.filename, item.text) };
  throw new Error(`unknown command: ${request.command}`);
});
process.stdout.write(JSON.stringify({ typescript: ts.version, results }));
