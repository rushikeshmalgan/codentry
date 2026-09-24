"""Tests the actual standalone CLI entry point as a real subprocess — this
is the literal command a human or CI job would run
(`python -m analysis.run <repo> <files>`), executed for real, not simulated.
"""

import json
import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).parent.parent  # services/ai-review
FIXTURES = SERVICE_ROOT / "analysis" / "fixtures"


def test_cli_runs_as_a_real_module_invocation():
    proc = subprocess.run(
        [sys.executable, "-m", "analysis.run", str(FIXTURES), "eslint_sample.js", "semgrep_sample.js"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout)
    assert output["overall_status"] == "completed"
    assert output["finding_count"] == 5


def test_cli_missing_arguments_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "analysis.run"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0


def test_cli_nonexistent_repo_path_completes_with_all_files_skipped():
    proc = subprocess.run(
        [sys.executable, "-m", "analysis.run", str(SERVICE_ROOT / "no-such-dir"), "a.js"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = json.loads(proc.stdout)
    assert output["skipped_files"] == [{"path": "a.js", "reason": "missing"}]
    assert output["finding_count"] == 0


def test_cli_makes_zero_ai_github_supabase_calls(tmp_path):
    """Structural proof, not a comment: a meta-path import blocker raises
    ImportError the instant anything tries to import supabase/jwt/anthropic/
    openai/httpx/postgrest/gotrue/app while running the CLI end-to-end
    against real fixtures. If the CLI's dependency graph ever grows an AI,
    GitHub, or Supabase call, this test fails loudly rather than the
    independence silently rotting away."""
    guard_script = f'''
import sys, json

# Running this script directly puts its own directory on sys.path[0], not
# services/ai-review — add it explicitly so `import analysis` resolves the
# real package rather than failing before the guard even gets exercised.
sys.path.insert(0, {str(SERVICE_ROOT)!r})

FORBIDDEN_ROOTS = {{"supabase", "jwt", "anthropic", "openai", "httpx", "postgrest", "gotrue", "app"}}

class ForbidImporter:
    def find_spec(self, name, path, target=None):
        root = name.split(".")[0]
        if root in FORBIDDEN_ROOTS:
            raise ImportError(f"FORBIDDEN MODULE IMPORTED BY STANDALONE CLI: {{name}}")
        return None

sys.meta_path.insert(0, ForbidImporter())

from analysis.run import main
sys.exit(main(sys.argv[1:]))
'''
    script_path = tmp_path / "guarded_run.py"
    script_path.write_text(guard_script, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(script_path), str(FIXTURES), "eslint_sample.js", "semgrep_sample.js"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    output = json.loads(proc.stdout)
    assert output["finding_count"] == 5
    assert "FORBIDDEN" not in proc.stderr


def test_cli_output_is_valid_json_matching_the_finding_schema():
    proc = subprocess.run(
        [sys.executable, "-m", "analysis.run", str(FIXTURES), "eslint_sample.js"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = json.loads(proc.stdout)
    required_keys = {
        "source", "category", "severity", "confidence", "title", "description",
        "file_path", "start_line", "end_line", "suggestion", "reasoning",
        "evidence_span", "dedup_hash",
    }
    for finding in output["findings"]:
        assert required_keys.issubset(finding.keys())
