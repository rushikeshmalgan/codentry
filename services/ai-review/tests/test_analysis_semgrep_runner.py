"""Real Semgrep execution against the checked-in fixtures and the local
baseline ruleset (no registry/network config), plus mocked-subprocess tests
for failure paths."""

import subprocess
from pathlib import Path

from analysis import semgrep_runner
from analysis.semgrep_runner import run_semgrep
from analysis.workspace import SourceFile, materialize

FIXTURES = Path(__file__).parent.parent / "analysis" / "fixtures"


def test_real_semgrep_run_against_semgrep_fixture():
    content = (FIXTURES / "semgrep_sample.js").read_text()
    with materialize([SourceFile(path="semgrep_sample.js", content=content)]) as workspace:
        result = run_semgrep(workspace, ["semgrep_sample.js"])

    assert result.status == "ok"
    check_ids = sorted(r["check_id"].rsplit(".", 1)[-1] for r in result.results)
    assert check_ids == ["eval-usage", "hardcoded-secret", "sql-string-concatenation"]


def test_real_semgrep_run_against_clean_fixture_has_no_results():
    content = (FIXTURES / "clean_sample.js").read_text()
    with materialize([SourceFile(path="clean_sample.js", content=content)]) as workspace:
        result = run_semgrep(workspace, ["clean_sample.js"])

    assert result.status == "ok"
    assert result.results == []


def test_real_semgrep_run_against_eslint_fixture_has_no_results():
    """Cross-check: the ESLint fixture shouldn't accidentally trip any
    Semgrep rule, keeping the two fixtures' finding counts cleanly additive."""
    content = (FIXTURES / "eslint_sample.js").read_text()
    with materialize([SourceFile(path="eslint_sample.js", content=content)]) as workspace:
        result = run_semgrep(workspace, ["eslint_sample.js"])

    assert result.results == []


def test_semgrep_skips_when_no_files():
    with materialize([]) as workspace:
        result = run_semgrep(workspace, [])
    assert result.status == "skipped"


def test_semgrep_unavailable_when_not_on_path(monkeypatch):
    monkeypatch.setattr(semgrep_runner.shutil, "which", lambda _name: None)
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])
    assert result.status == "error"
    assert "not found" in result.error_message.lower()


def test_semgrep_timeout_is_handled_without_raising(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="semgrep", timeout=30)

    monkeypatch.setattr(semgrep_runner.subprocess, "run", fake_run)
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])

    assert result.status == "timeout"
    assert "30" in result.error_message


def test_semgrep_malformed_json_output_is_handled(monkeypatch):
    class FakeProc:
        returncode = 2
        stdout = "not json {{{"
        stderr = "fatal"

    monkeypatch.setattr(semgrep_runner.subprocess, "run", lambda *a, **k: FakeProc())
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])

    assert result.status == "error"
    assert "non-JSON" in result.error_message
