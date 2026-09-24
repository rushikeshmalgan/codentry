"""Real ESLint execution against the checked-in fixtures (no mocking of the
tool itself) plus mocked-subprocess tests for failure paths that would
otherwise be slow/flaky to trigger for real (timeouts) or aren't reachable
without deliberately breaking the local environment (tool unavailable)."""

import subprocess
from pathlib import Path

from analysis import eslint_runner
from analysis.eslint_runner import run_eslint
from analysis.workspace import SourceFile, materialize

FIXTURES = Path(__file__).parent.parent / "analysis" / "fixtures"


def test_real_eslint_run_against_eslint_fixture():
    content = (FIXTURES / "eslint_sample.js").read_text()
    with materialize([SourceFile(path="eslint_sample.js", content=content)]) as workspace:
        result = run_eslint(workspace, ["eslint_sample.js"])

    assert result.status == "ok"
    assert result.used_repo_config is False
    assert len(result.file_reports) == 1
    rule_ids = sorted(m["ruleId"] for m in result.file_reports[0]["messages"])
    assert rule_ids == ["no-undef", "no-unused-vars"]


def test_real_eslint_run_against_clean_fixture_has_no_messages():
    content = (FIXTURES / "clean_sample.js").read_text()
    with materialize([SourceFile(path="clean_sample.js", content=content)]) as workspace:
        result = run_eslint(workspace, ["clean_sample.js"])

    assert result.status == "ok"
    assert result.file_reports[0]["messages"] == []


def test_eslint_skips_when_no_analyzable_files():
    with materialize([SourceFile(path="README.md", content="# hi")]) as workspace:
        result = run_eslint(workspace, ["README.md"])
    assert result.status == "skipped"


def test_eslint_unavailable_when_node_missing(monkeypatch):
    monkeypatch.setattr(eslint_runner.shutil, "which", lambda _name: None)
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])
    assert result.status == "error"
    assert "node" in result.error_message.lower() or "unavailable" in result.error_message.lower()


def test_eslint_timeout_is_handled_without_raising(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="eslint", timeout=30)

    monkeypatch.setattr(eslint_runner.subprocess, "run", fake_run)
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])

    assert result.status == "timeout"
    assert "30" in result.error_message


def test_eslint_malformed_json_output_is_handled(monkeypatch):
    class FakeProc:
        returncode = 2
        stdout = "not json at all {{{"
        stderr = "fatal error"

    monkeypatch.setattr(eslint_runner.subprocess, "run", lambda *a, **k: FakeProc())
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])

    assert result.status == "error"
    assert "non-JSON" in result.error_message


def test_eslint_falls_back_to_baseline_when_repo_config_is_broken():
    """A repo config referencing a plugin outside Codentry's pinned baseline
    install must fail closed and fall back, per the security design in
    eslint_runner.py's module docstring — never trigger installing the
    repo's own tooling."""
    broken_config = SourceFile(
        path=".eslintrc.json",
        content='{"extends": ["plugin:some-plugin-nobody-installed/recommended"]}',
    )
    sample = SourceFile(path="eslint_sample.js", content=(FIXTURES / "eslint_sample.js").read_text())

    with materialize([broken_config, sample]) as workspace:
        result = run_eslint(workspace, ["eslint_sample.js"])

    assert result.status == "ok"
    assert result.used_repo_config is False
    rule_ids = sorted(m["ruleId"] for m in result.file_reports[0]["messages"])
    assert rule_ids == ["no-undef", "no-unused-vars"]


def test_eslint_uses_repo_config_when_it_loads_successfully():
    """A repo config that loads fine (even if stricter/different) is honored."""
    repo_config = SourceFile(
        path=".eslintrc.json",
        content='{"env": {"node": true}, "rules": {"no-console": "error"}}',
    )
    sample = SourceFile(path="a.js", content="console.log('hi');\n")

    with materialize([repo_config, sample]) as workspace:
        result = run_eslint(workspace, ["a.js"])

    assert result.status == "ok"
    assert result.used_repo_config is True
    assert result.file_reports[0]["messages"][0]["ruleId"] == "no-console"
