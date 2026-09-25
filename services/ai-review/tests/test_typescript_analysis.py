"""Regression tests: TypeScript files must actually be linted.

Phase 0 rewrote the baseline config's `parser` entry to the parser package's
*directory*. @typescript-eslint/parser declares only an `exports` map (no
`main`), so require(<directory>) raised MODULE_NOT_FOUND and ESLint refused to
lint any batch that contained a .ts/.tsx file — for a JS/TS product, every
TypeScript pull request would have failed analysis. Every earlier fixture was
plain JavaScript, so nothing noticed. These tests run the real ESLint (no mocks)
on TypeScript.
"""

import subprocess

from analysis.eslint_runner import run_eslint
from analysis.static_analysis import analyze_source_files
from analysis.trusted_config import _TS_PARSER_PATH, build_effective_config
from analysis.workspace import SourceFile, materialize

TS_WITH_ANY = "export const loose: any = 1;\n\nexport function add(a: number, b: number): number {\n  return a + b;\n}\n"
JS_UNUSED = "const unused = 1;\nmodule.exports = {};\n"


def test_the_configured_typescript_parser_is_a_loadable_file():
    assert _TS_PARSER_PATH.is_file(), _TS_PARSER_PATH
    proc = subprocess.run(
        ["node", "-e", "require(process.argv[1])", str(_TS_PARSER_PATH)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


def test_the_effective_config_points_the_ts_override_at_that_file():
    overrides = build_effective_config()["overrides"]
    assert [o["parser"] for o in overrides] == [str(_TS_PARSER_PATH)]


def test_real_eslint_lints_a_typescript_file():
    with materialize([SourceFile("src/a.ts", TS_WITH_ANY)]) as workspace:
        result = run_eslint(workspace, ["src/a.ts"])
    assert result.status == "ok", result.error_message
    rules = [m["ruleId"] for m in result.file_reports[0]["messages"]]
    assert rules == ["@typescript-eslint/no-explicit-any"]


def test_a_mixed_javascript_and_typescript_batch_is_analyzed_as_a_whole():
    result = analyze_source_files(
        [SourceFile("src/a.ts", TS_WITH_ANY), SourceFile("lib/b.js", JS_UNUSED)],
        None,
        "ts-regression",
    )
    assert result.eslint_status == "ok", result.eslint_error
    assert result.analysis_complete
    found = sorted((f.file_path, f.title) for f in result.findings if f.source == "ESLINT")
    assert found == [
        ("lib/b.js", "no-unused-vars"),
        ("src/a.ts", "@typescript-eslint/no-explicit-any"),
    ]


def test_a_clean_typescript_file_yields_no_findings_and_a_clean_status():
    clean = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
    result = analyze_source_files([SourceFile("src/clean.ts", clean)], None, "ts-regression")
    assert result.eslint_status == "ok" and result.findings == []
