"""Executable proof-of-concept tests for the Phase 0 security findings.

Each test below encodes an attack a hostile pull request could mount against
Codentry's own analysis pipeline. They were written BEFORE the fixes and run
against the unmodified Phase 3 code, where the ones marked "fail-before"
failed (see docs/phase0-hardening-report.md for the recorded before/after
output). They must pass now and must never be weakened.

Every "payload" here is harmless by construction: it writes a marker file
under pytest's tmp_path (or reads a canary env var created by the test) — it
never touches anything outside the temp directory. A test passes only when
the payload did NOT execute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from analysis.static_analysis import analyze_source_files
from analysis.workspace import SourceFile, WorkspaceLimitError, materialize


def _js_path(p: Path) -> str:
    """A path safe to embed inside a JS string literal on any platform."""
    return json.dumps(str(p).replace("\\", "/"))


def _rule_ids(result) -> list[str]:
    return sorted(f.title for f in result.findings)


# --- 1. Repository-controlled config executes code (CRITICAL) -----------------


def test_poc_repo_eslintrc_js_is_never_executed(tmp_path):
    marker = tmp_path / "eslintrc_js_executed.txt"
    evil = (
        f"require('fs').writeFileSync({_js_path(marker)}, 'pwned');\n"
        "module.exports = { rules: {} };\n"
    )
    files = [
        SourceFile(path=".eslintrc.js", content=evil),
        SourceFile(path="a.js", content="var unused = 1;\n"),
    ]

    result = analyze_source_files(files)

    assert not marker.exists(), "PR-supplied .eslintrc.js was executed by the analyzer"
    # ...and the PR's own config must not have silenced the baseline either.
    assert "no-unused-vars" in _rule_ids(result)


def test_poc_repo_json_config_parser_is_never_loaded(tmp_path):
    marker = tmp_path / "parser_loaded.txt"
    evil_parser = (
        f"require('fs').writeFileSync({_js_path(marker)}, 'pwned');\n"
        "module.exports = require('espree');\n"
    )
    files = [
        SourceFile(path=".eslintrc.json", content='{"parser": "./evil-parser.js"}'),
        SourceFile(path="evil-parser.js", content=evil_parser),
        SourceFile(path="a.js", content="var unused = 1;\n"),
    ]

    analyze_source_files(files)

    assert not marker.exists(), "PR-supplied ESLint parser was require()d by the analyzer"


def test_poc_repo_config_extends_relative_js_is_never_loaded(tmp_path):
    marker = tmp_path / "extends_loaded.txt"
    evil = (
        f"require('fs').writeFileSync({_js_path(marker)}, 'pwned');\n"
        "module.exports = { rules: {} };\n"
    )
    files = [
        SourceFile(path=".eslintrc.json", content='{"extends": ["./evil-shared-config.js"]}'),
        SourceFile(path="evil-shared-config.js", content=evil),
        SourceFile(path="a.js", content="var unused = 1;\n"),
    ]

    analyze_source_files(files)

    assert not marker.exists(), "PR-supplied `extends` target was executed by the analyzer"


# --- 2. Subprocess inherits every server secret (CRITICAL) -------------------


def test_poc_server_secrets_are_not_visible_to_repo_controlled_code(tmp_path, monkeypatch):
    canaries = {
        "SUPABASE_SERVICE_ROLE_KEY": "canary-supabase-service-role-key",
        "GITHUB_PRIVATE_KEY": "canary-github-private-key",
        "CODENTRY_INTERNAL_WEBHOOK_SECRET": "canary-internal-secret",
        "CLAUDE_API_KEY": "canary-claude-api-key",
    }
    for name, value in canaries.items():
        monkeypatch.setenv(name, value)

    marker = tmp_path / "env_dump.json"
    evil = (
        f"require('fs').writeFileSync({_js_path(marker)}, JSON.stringify(process.env));\n"
        "module.exports = { rules: {} };\n"
    )
    files = [
        SourceFile(path=".eslintrc.js", content=evil),
        SourceFile(path="a.js", content="var unused = 1;\n"),
    ]

    analyze_source_files(files)

    if marker.exists():
        dumped = marker.read_text(encoding="utf-8")
        leaked = [name for name, value in canaries.items() if value in dumped]
        pytest.fail(f"secrets visible to repository-controlled code: {leaked}")


# --- 3. File path becomes a command-line option (HIGH) ------------------------


def test_poc_dash_prefixed_filename_is_data_not_an_option():
    """`--bogus-option.js` is a legal git path. Passed to ESLint/Semgrep
    unprefixed it is parsed as a flag, the run errors out, and the file's
    findings silently vanish — a trivial way to evade review."""
    files = [SourceFile(path="--bogus-option.js", content="var unused = 1;\n")]

    result = analyze_source_files(files)

    assert result.eslint_status == "ok", result.eslint_error
    assert "no-unused-vars" in _rule_ids(result)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows strips the trailing dot of the directory name `--parser=.`; "
    "POSIX-only PoC (exercised by CI on ubuntu-latest).",
)
def test_poc_option_smuggling_via_path_cannot_load_a_parser(tmp_path):
    marker = tmp_path / "smuggled_parser.txt"
    evil = (
        f"require('fs').writeFileSync({_js_path(marker)}, 'pwned');\n"
        "module.exports = require('espree');\n"
    )
    # argv element `--parser=./evil.js` == ESLint's --parser option.
    files = [SourceFile(path="--parser=./evil.js", content=evil)]

    analyze_source_files(files)

    assert not marker.exists()


# --- 4. Path traversal / absolute / drive paths (HIGH) ------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.js",
        "a/../../escape.js",
        "..\\escape.js",
        "/abs/escape.js",
        "C:escape.js",
        "\\\\server\\share\\escape.js",
        "nul\x00.js",
    ],
)
def test_poc_unsafe_paths_never_reach_the_filesystem(bad_path):
    try:
        with materialize([SourceFile(path=bad_path, content="var x = 1;\n")]) as workspace:
            written = [p for p in workspace.rglob("*") if p.is_file()]
    except WorkspaceLimitError:
        return  # refusing outright is the strictest acceptable outcome
    assert written == [], f"unsafe path {bad_path!r} was written: {written}"


def test_unsafe_paths_are_skipped_and_reported_by_the_pipeline_not_analyzed():
    result = analyze_source_files(
        [
            SourceFile(path="../escape.js", content="var unused = 1;\n"),
            SourceFile(path="ok.js", content="var unused = 1;\n"),
        ]
    )
    assert {"path": "../escape.js", "reason": "unsafe_path"} in result.skipped_files
    assert {f.file_path for f in result.findings} == {"ok.js"}
    assert result.analysis_complete is False
    assert "unsafe_path" in result.incomplete_reasons


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_poc_absolute_path_cannot_write_outside_workspace(tmp_path, separator):
    """The real Windows failure mode, reproduced against the unmodified
    Phase 3 code (it wrote C:/Windows/Temp/escape.js): pathlib discards the
    workspace prefix when the joined path is absolute, so a drive-absolute
    path is an arbitrary file write. The harmless target lives under tmp_path
    and is checked directly, not just inside the workspace."""
    outside = tmp_path / "outside" / "escape.js"
    abs_path = str(outside).replace("\\", separator).replace("/", separator)

    try:
        with materialize([SourceFile(path=abs_path, content="var x = 1;\n")]):
            pass
    except WorkspaceLimitError:
        pass

    assert not outside.exists(), "materialize() wrote outside its workspace"


# --- 5. Config / control files must never be written into the workspace ------


@pytest.mark.parametrize(
    "control_file",
    [
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintignore",
        ".semgrepignore",
        ".semgrep.yml",
        "eslint.config.js",
        "package.json",
        "tsconfig.json",
        "sub/dir/.eslintrc.js",
    ],
)
def test_poc_control_files_are_not_materialized(control_file):
    files = [
        SourceFile(path=control_file, content="{}"),
        SourceFile(path="a.js", content="var x = 1;\n"),
    ]
    with materialize(files) as workspace:
        assert not (workspace / control_file).exists()
        assert (workspace / "a.js").exists()


# --- 6. A PR must not be able to hide its own findings ------------------------


def test_poc_eslintignore_cannot_hide_findings():
    files = [
        SourceFile(path=".eslintignore", content="*.js\n"),
        SourceFile(path="a.js", content="var unused = 1;\n"),
    ]
    result = analyze_source_files(files)
    assert "no-unused-vars" in _rule_ids(result)


def test_poc_semgrepignore_cannot_hide_findings():
    files = [
        SourceFile(path=".semgrepignore", content="*.js\n"),
        SourceFile(path="a.js", content='eval("1+1");\n'),
    ]
    result = analyze_source_files(files)
    assert "eval-usage" in _rule_ids(result)


def test_poc_inline_eslint_disable_cannot_hide_findings():
    files = [SourceFile(path="a.js", content="/* eslint-disable */\nvar unused = 1;\n")]
    result = analyze_source_files(files)
    assert "no-unused-vars" in _rule_ids(result)


def test_poc_inline_nosemgrep_cannot_hide_findings():
    files = [SourceFile(path="a.js", content='eval("1+1"); // nosemgrep\n')]
    result = analyze_source_files(files)
    assert "eval-usage" in _rule_ids(result)


def test_poc_repo_config_cannot_disable_baseline_rules():
    files = [
        SourceFile(path=".eslintrc.json", content='{"root": true, "rules": {"no-unused-vars": "off"}}'),
        SourceFile(path="a.js", content="var unused = 1;\n"),
    ]
    result = analyze_source_files(files)
    assert "no-unused-vars" in _rule_ids(result)
