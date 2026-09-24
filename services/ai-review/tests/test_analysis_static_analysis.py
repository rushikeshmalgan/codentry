"""The Phase 3 Definition-of-Done test lives here: a fixture set with a known
N ESLint violations and M Semgrep matches must produce exactly N+M findings,
correctly attributed and located. Also covers the error-handling matrix
(missing file, unsupported file type, empty diff, too many files)."""

from pathlib import Path

from analysis import eslint_runner, semgrep_runner
from analysis.static_analysis import run_static_analysis

FIXTURES = Path(__file__).parent.parent / "analysis" / "fixtures"


def test_definition_of_done_exactly_n_plus_m_findings():
    """N=2 (ESLint: no-unused-vars, no-undef) + M=3 (Semgrep: hardcoded-secret,
    eval-usage, sql-string-concatenation) = 5, verified against real tool
    execution, not mocked output."""
    result = run_static_analysis(str(FIXTURES), ["eslint_sample.js", "semgrep_sample.js"])

    assert result.overall_status == "completed"
    assert result.eslint_status == "ok"
    assert result.semgrep_status == "ok"
    assert len(result.findings) == 5

    by_source = {"ESLINT": 0, "SEMGREP": 0}
    for f in result.findings:
        by_source[f.source] += 1
    assert by_source == {"ESLINT": 2, "SEMGREP": 3}

    eslint_files = {f.file_path for f in result.findings if f.source == "ESLINT"}
    semgrep_files = {f.file_path for f in result.findings if f.source == "SEMGREP"}
    assert eslint_files == {"eslint_sample.js"}
    assert semgrep_files == {"semgrep_sample.js"}

    eslint_lines = sorted(f.start_line for f in result.findings if f.source == "ESLINT")
    assert eslint_lines == [2, 3]
    semgrep_lines = sorted(f.start_line for f in result.findings if f.source == "SEMGREP")
    assert semgrep_lines == [1, 4, 8]


def test_clean_fixture_produces_zero_findings():
    result = run_static_analysis(str(FIXTURES), ["clean_sample.js"])
    assert result.overall_status == "completed"
    assert result.findings == []


def test_empty_file_list_completes_with_zero_findings():
    result = run_static_analysis(str(FIXTURES), [])
    assert result.overall_status == "completed"
    assert result.findings == []
    assert result.eslint_status == "skipped"
    assert result.semgrep_status == "skipped"


def test_missing_file_is_skipped_not_errored():
    result = run_static_analysis(str(FIXTURES), ["does_not_exist.js", "clean_sample.js"])
    assert result.overall_status == "completed"
    assert {"path": "does_not_exist.js", "reason": "missing"} in result.skipped_files


def test_unsupported_binary_file_is_skipped_safely(tmp_path):
    binary_file = tmp_path / "image.png"
    binary_file.write_bytes(bytes(range(256)))
    result = run_static_analysis(str(tmp_path), ["image.png"])
    assert result.overall_status == "completed"
    assert result.skipped_files == [{"path": "image.png", "reason": "binary_or_undecodable"}]


def test_too_many_files_fails_safely_without_hanging(tmp_path):
    from analysis.workspace import MAX_FILES

    for i in range(MAX_FILES + 5):
        (tmp_path / f"f{i}.js").write_text("const x = 1;")
    files = [f"f{i}.js" for i in range(MAX_FILES + 5)]

    result = run_static_analysis(str(tmp_path), files)

    assert result.overall_status == "failed"
    assert "too many" in (result.eslint_error or "").lower()


def test_partial_failure_when_only_one_tool_fails(monkeypatch):
    """If Semgrep is unavailable but ESLint still runs, the run is a
    'partial_failure', not a full 'failed' — findings from the tool that DID
    run are preserved, per section 13's "do not silently report success but
    also don't discard what succeeded" requirement.

    Note: eslint_runner and semgrep_runner both `import shutil`, so they
    share the exact same module object — patching `shutil.which` on one
    patches it everywhere. The lambda must be selective by name rather than
    blanket-returning None, or it silently breaks ESLint's own `which("node")`
    lookup too (which is exactly what happened before this comment existed).
    """
    real_which = semgrep_runner.shutil.which

    def selective_which(name: str, *args, **kwargs) -> str | None:
        return None if name == "semgrep" else real_which(name, *args, **kwargs)

    monkeypatch.setattr(semgrep_runner.shutil, "which", selective_which)

    result = run_static_analysis(str(FIXTURES), ["eslint_sample.js"])

    assert result.overall_status == "partial_failure"
    assert result.eslint_status == "ok"
    assert result.semgrep_status == "error"
    assert len(result.findings) == 2  # the ESLint findings are still there
    assert result.error_summary is not None
    assert "semgrep" in result.error_summary.lower()


def test_full_failure_when_both_tools_unavailable(monkeypatch):
    monkeypatch.setattr(eslint_runner.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(semgrep_runner.shutil, "which", lambda *a, **k: None)

    result = run_static_analysis(str(FIXTURES), ["eslint_sample.js"])

    assert result.overall_status == "failed"
    assert result.findings == []


def test_finding_volume_is_capped_and_marked_incomplete_never_silently_truncated(monkeypatch):
    from analysis import static_analysis
    from analysis.workspace import SourceFile

    monkeypatch.setattr(static_analysis, "MAX_FINDINGS", 2)
    content = "var a = 1;\nvar b = 2;\nvar c = 3;\nvar d = 4;\n"

    result = static_analysis.analyze_source_files([SourceFile("many.js", content)])

    assert len(result.findings) == 2
    assert {"path": "*", "reason": "findings_truncated"} in result.skipped_files
    assert result.analysis_complete is False
    assert "findings_truncated" in result.incomplete_reasons


def test_semgrep_reported_file_errors_make_the_analysis_incomplete(monkeypatch):
    from analysis import static_analysis
    from analysis.semgrep_runner import SemgrepRunResult
    from analysis.workspace import SourceFile

    monkeypatch.setattr(
        static_analysis,
        "run_semgrep",
        lambda *a, **k: SemgrepRunResult(status="ok", results=[], tool_error_paths=["a.js"]),
    )

    result = static_analysis.analyze_source_files([SourceFile("a.js", "const x = 1;\nmodule.exports = { x };\n")])

    assert result.overall_status == "completed"  # both tools "ran"...
    assert result.analysis_complete is False  # ...but Semgrep could not fully process a.js
    assert {"path": "a.js", "reason": "tool_error"} in result.skipped_files


def test_a_complete_clean_run_reports_analysis_complete_with_reproducibility_metadata():
    from analysis.static_analysis import analyze_source_files
    from analysis.workspace import SourceFile

    clean = "function add(a, b) {\n  return a + b;\n}\nmodule.exports = { add };\n"
    result = analyze_source_files([SourceFile("clean.js", clean), SourceFile("README.md", "# hi")])

    assert result.analysis_complete is True  # a skipped README is not incompleteness
    meta = result.meta()
    assert meta["ruleset_sha256"] and len(meta["ruleset_sha256"]) == 64
    assert meta["baseline_config_sha256"] and meta["eslint_version"] and meta["semgrep_version"]
    assert meta["config_source"] == "baseline" and meta["identity_version"] == 2
    assert meta["skipped_by_reason"] == {"not_analyzable_type": 1}
