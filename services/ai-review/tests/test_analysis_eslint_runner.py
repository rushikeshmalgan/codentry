"""Real ESLint execution against the checked-in fixtures (no mocking of the
tool itself) plus mocked-subprocess tests for failure paths that would
otherwise be slow/flaky to trigger for real (timeouts) or aren't reachable
without deliberately breaking the local environment (tool unavailable)."""

from pathlib import Path

from analysis import eslint_runner
from analysis.eslint_runner import build_command, run_eslint
from analysis.subprocess_env import ToolOutputTooLargeError, ToolProcessResult, ToolTimeoutError
from analysis.trusted_config import sanitize_overlay
from analysis.workspace import SourceFile, materialize

FIXTURES = Path(__file__).parent.parent / "analysis" / "fixtures"


def test_real_eslint_run_against_eslint_fixture():
    content = (FIXTURES / "eslint_sample.js").read_text()
    with materialize([SourceFile(path="eslint_sample.js", content=content)]) as workspace:
        result = run_eslint(workspace, ["eslint_sample.js"])

    assert result.status == "ok"
    assert result.config_source == "baseline"
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
        raise ToolTimeoutError("exceeded 30s")

    monkeypatch.setattr(eslint_runner, "run_tool", fake_run)
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])

    assert result.status == "timeout"
    assert "30" in result.error_message


def test_eslint_malformed_json_output_is_handled(monkeypatch):
    monkeypatch.setattr(
        eslint_runner,
        "run_tool",
        lambda *a, **k: ToolProcessResult(2, "not json at all {{{", "fatal error"),
    )
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])

    assert result.status == "error"
    assert "non-JSON" in result.error_message


def test_eslint_output_too_large_is_an_error_not_a_crash(monkeypatch):
    def fake_run(*args, **kwargs):
        raise ToolOutputTooLargeError("output exceeded 20000000 bytes")

    monkeypatch.setattr(eslint_runner, "run_tool", fake_run)
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])
    assert result.status == "error"
    assert "exceeded" in result.error_message


def test_eslint_command_is_hardened_and_paths_are_never_options():
    cmd = build_command("node", Path("cfg.json"), ["--evil.js", "src/a.ts"])

    for flag in ("--no-eslintrc", "--no-inline-config", "--no-ignore"):
        assert flag in cmd
    assert "--resolve-plugins-relative-to" in cmd
    # Everything after the "--" terminator is a path, and none can start with "-".
    terminator = cmd.index("--")
    paths = cmd[terminator + 1 :]
    assert paths == ["./--evil.js", "./src/a.ts"]
    assert not any(p.startswith("-") for p in paths)
    # The only config is the generated one; the workspace is never consulted.
    assert cmd.count("-c") == 1


def test_eslint_env_passed_to_the_tool_is_scrubbed(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "canary-should-not-leak")
    captured = {}

    def fake_run(cmd, *, cwd, env, timeout, **kwargs):
        captured["env"] = dict(env)
        return ToolProcessResult(0, "[]", "")

    monkeypatch.setattr(eslint_runner, "run_tool", fake_run)
    with materialize([SourceFile(path="a.js", content="const x = 1;")]) as workspace:
        result = run_eslint(workspace, ["a.js"])

    assert result.status == "ok"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in captured["env"]
    assert not any("canary-should-not-leak" in v for v in captured["env"].values())


def test_repository_eslintrc_is_ignored_baseline_still_applies():
    """Behavior change from Phase 3 (a deliberate security fix): a repo config
    is no longer honored - not even a harmless one. The baseline decides."""
    repo_config = SourceFile(
        path=".eslintrc.json",
        content='{"root": true, "rules": {"no-unused-vars": "off", "no-console": "error"}}',
    )
    sample = SourceFile(path="a.js", content="var unused = 1;\nconsole.log('hi');\n")

    from analysis.static_analysis import analyze_source_files

    result = analyze_source_files([repo_config, sample])

    rule_ids = sorted(f.title for f in result.findings if f.source == "ESLINT")
    assert "no-unused-vars" in rule_ids  # repo tried to turn it off; baseline wins
    assert "no-console" not in rule_ids  # repo tried to turn it on; ignored
    assert result.config_source == "baseline"


def test_trusted_base_overlay_can_add_rules():
    overlay = sanitize_overlay(
        '{"rules": {"no-console": "error"}, "env": {"node": true}}',
        source_ref="basesha:.eslintrc.json",
    )
    sample = SourceFile(path="a.js", content="console.log('hi');\n")

    with materialize([sample]) as workspace:
        result = run_eslint(workspace, ["a.js"], overlay=overlay)

    assert result.status == "ok"
    assert result.config_source == "baseline+base_overlay"
    assert result.file_reports[0]["messages"][0]["ruleId"] == "no-console"
