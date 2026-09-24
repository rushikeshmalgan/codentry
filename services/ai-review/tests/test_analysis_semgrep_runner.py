"""Real Semgrep execution against the checked-in fixtures and the local
baseline ruleset (no registry/network config), plus mocked-subprocess tests
for failure paths."""

from pathlib import Path

from analysis import semgrep_runner
from analysis.semgrep_runner import build_command, run_semgrep
from analysis.subprocess_env import ToolProcessResult, ToolTimeoutError
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
    monkeypatch.setattr(semgrep_runner.shutil, "which", lambda *a, **k: None)
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])
    assert result.status == "error"
    assert "not found" in result.error_message.lower()


def test_semgrep_timeout_is_handled_without_raising(monkeypatch):
    def fake_run(*args, **kwargs):
        raise ToolTimeoutError("exceeded 30s")

    monkeypatch.setattr(semgrep_runner, "run_tool", fake_run)
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])

    assert result.status == "timeout"
    assert "30" in result.error_message


def test_semgrep_malformed_json_output_is_handled(monkeypatch):
    monkeypatch.setattr(
        semgrep_runner, "run_tool", lambda *a, **k: ToolProcessResult(2, "not json {{{", "fatal")
    )
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])

    assert result.status == "error"
    assert "non-JSON" in result.error_message


def test_semgrep_command_is_hardened_and_paths_are_never_options():
    cmd = build_command("semgrep", ["--evil.js", "src/a.ts"])

    for flag in (
        "--disable-nosem",
        "--no-git-ignore",
        "--max-memory",
        "--timeout",
        "--max-target-bytes",
        "--disable-version-check",
    ):
        assert flag in cmd
    assert cmd[cmd.index("--metrics") + 1] == "off"
    terminator = cmd.index("--")
    paths = cmd[terminator + 1 :]
    assert paths == ["./--evil.js", "./src/a.ts"]
    # Only the local production ruleset; never a registry pack (network fetch).
    configs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--config"]
    assert len(configs) == 1 and configs[0].endswith("production.yml")


def test_semgrep_env_passed_to_the_tool_is_scrubbed(monkeypatch):
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "canary-should-not-leak")
    captured = {}

    def fake_run(cmd, *, cwd, env, timeout, **kwargs):
        captured["env"] = dict(env)
        return ToolProcessResult(0, '{"results": [], "errors": []}', "")

    monkeypatch.setattr(semgrep_runner, "run_tool", fake_run)
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])

    assert result.status == "ok"
    assert "GITHUB_PRIVATE_KEY" not in captured["env"]
    assert not any("canary-should-not-leak" in v for v in captured["env"].values())


def test_semgrep_reported_file_errors_are_surfaced_not_swallowed(monkeypatch):
    payload = '{"results": [], "errors": [{"path": "./a.js", "type": "PartialParsing"}]}'
    monkeypatch.setattr(
        semgrep_runner, "run_tool", lambda *a, **k: ToolProcessResult(2, payload, "")
    )
    with materialize([SourceFile(path="a.js", content="eval(x);")]) as workspace:
        result = run_semgrep(workspace, ["a.js"])
    assert result.status == "ok"
    assert result.tool_error_paths == ["a.js"]
