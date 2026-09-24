"""Scrubbed environment and bounded process execution."""

import json
import shutil
import sys

import pytest

from analysis.subprocess_env import (
    ToolOutputTooLargeError,
    ToolTimeoutError,
    run_tool,
    scrubbed_env,
    tool_sandbox,
)

SECRET_NAMES = [
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_URL",
    "GITHUB_PRIVATE_KEY",
    "GITHUB_APP_ID",
    "CODENTRY_INTERNAL_WEBHOOK_SECRET",
    "CLAUDE_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
    "NODE_OPTIONS",
    "PYTHONPATH",
]


def test_scrubbed_env_never_copies_secrets_or_unlisted_variables(monkeypatch):
    for name in SECRET_NAMES:
        monkeypatch.setenv(name, "canary-" + name)
    monkeypatch.setenv("SOME_RANDOM_VARIABLE", "canary-random")

    env = scrubbed_env()

    assert not any("canary-" in value for value in env.values())
    # NODE_OPTIONS is set explicitly by us (a heap cap), never inherited.
    assert env["NODE_OPTIONS"].startswith("--max-old-space-size=")
    assert "PYTHONPATH" not in env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in env


def test_scrubbed_env_keeps_only_what_the_runtimes_need(monkeypatch):
    monkeypatch.setenv("PATH", "/bin:/usr/bin")
    env = scrubbed_env()
    assert env["PATH"] == "/bin:/usr/bin"
    assert env["SEMGREP_SEND_METRICS"] == "off"


def test_sandbox_redirects_home_and_temp_outside_the_workspace():
    with tool_sandbox() as sandbox:
        env = scrubbed_env(sandbox)
        assert env["HOME"] == str(sandbox.home)
        assert env["TEMP"] == str(sandbox.tmp)
        assert sandbox.home.is_dir() and sandbox.config_dir.is_dir()
        captured = sandbox.root
    assert not captured.exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_real_child_process_cannot_see_server_secrets(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "canary-real-child")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "canary-real-child")
    with tool_sandbox() as sandbox:
        result = run_tool(
            [shutil.which("node"), "-e", "console.log(JSON.stringify(process.env))"],
            cwd=sandbox.root,
            env=scrubbed_env(sandbox),
            timeout=30,
        )
    dumped = json.loads(result.stdout)
    assert "SUPABASE_SERVICE_ROLE_KEY" not in dumped
    assert "GITHUB_PRIVATE_KEY" not in dumped
    assert "canary-real-child" not in result.stdout


def test_run_tool_enforces_the_timeout_and_kills_the_process(tmp_path):
    with pytest.raises(ToolTimeoutError):
        run_tool(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            env=scrubbed_env(),
            timeout=1,
        )


def test_run_tool_caps_output_size(tmp_path):
    with pytest.raises(ToolOutputTooLargeError):
        run_tool(
            [sys.executable, "-c", "print('x' * 5000)"],
            cwd=tmp_path,
            env=scrubbed_env(),
            timeout=30,
            max_output_bytes=1000,
        )


def test_run_tool_captures_output_and_closes_stdin(tmp_path):
    result = run_tool(
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
        cwd=tmp_path,
        env=scrubbed_env(),
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "''"  # stdin is /dev/null, not inherited
