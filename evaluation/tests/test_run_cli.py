"""The literal command a person runs: `python -m evaluation.run --arm A ...`, as a
real subprocess with the real tools. Covers the Day 1 acceptance criteria:
byte-identical output across two runs, and run.json recording every version and
hash needed to reproduce.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.case import discover_case_dirs, manifest_sha256
from evaluation.tests.helpers import COMMITTED_CASES, REPO_ROOT, document, write_case

SERVICE_ROOT = REPO_ROOT / "services" / "ai-review"
CASE_IDS = ("fx-001-new-eval-with-existing-noise", "fx-002-renamed-shifted-preexisting-eval")


def run_cli(*args: str, timeout: int = 400) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SERVICE_ROOT), env.get("PYTHONPATH", "")) if p
    )
    # PYTHONHASHSEED is deliberately left as the environment has it (normally random):
    # determinism must not depend on set/dict hashing order.
    return subprocess.run(
        [sys.executable, "-m", "evaluation.run", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout,
    )


@pytest.fixture(scope="module")
def fixture_cases(tmp_path_factory):
    """Only the hand-made fixtures. The committed cases directory also holds the
    mutation corpus (well over a hundred cases, tens of minutes of real analysis),
    which these CLI tests must not run."""
    cases = tmp_path_factory.mktemp("fixture-cases")
    for case_id in CASE_IDS:
        shutil.copytree(COMMITTED_CASES / case_id, cases / case_id)
    return cases


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory, fixture_cases):
    base = tmp_path_factory.mktemp("runs")
    out1, out2 = base / "one", base / "two"
    first = run_cli("--arm", "A", "--cases", str(fixture_cases), "--out", str(out1))
    second = run_cli("--arm", "A", "--cases", str(fixture_cases), "--out", str(out2))
    return first, second, out1, out2


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_both_runs_succeed_and_print_the_arm_label(two_runs):
    first, second, _, _ = two_runs
    for proc in (first, second):
        assert proc.returncode == 0, proc.stderr
        assert "ESLint + Codentry baseline ruleset (6 rules) run with Semgrep" in proc.stdout
        assert "results_sha256:" in proc.stdout


def test_two_runs_produce_byte_identical_output(two_runs):
    _, _, out1, out2 = two_runs
    for relative in ["run.json", *[f"{cid}/result.json" for cid in CASE_IDS]]:
        assert (out1 / relative).read_bytes() == (out2 / relative).read_bytes(), relative
    assert sorted(p.name for p in out1.iterdir()) == sorted(p.name for p in out2.iterdir())


def test_output_hash_is_identical_across_runs_and_matches_the_files(two_runs):
    first, second, out1, out2 = two_runs
    run1, run2 = load(out1 / "run.json"), load(out2 / "run.json")
    assert run1["results_sha256"] == run2["results_sha256"]
    for proc, run in ((first, run1), (second, run2)):
        assert f"results_sha256: {run['results_sha256']}" in proc.stdout
    # recompute the run-level hash from the bytes on disk
    entries = []
    for entry in run1["cases"]:
        digest = hashlib.sha256((out1 / entry["id"] / "result.json").read_bytes()).hexdigest()
        assert digest == entry["result_sha256"]
        entries.append([entry["id"], digest])
    canonical = (json.dumps(entries, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    assert hashlib.sha256(canonical).hexdigest() == run1["results_sha256"]


def test_run_json_records_every_version_and_hash_needed_to_reproduce(two_runs, fixture_cases):
    _, _, out1, _ = two_runs
    run = load(out1 / "run.json")
    tools = run["tools"]
    for key in ("eslint_version", "semgrep_version", "node_version", "python_version", "platform"):
        assert tools[key], key
    for key in ("ruleset_sha256", "baseline_config_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", tools[key]), key
    assert tools["identity_version"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", run["case_manifest_sha256"])
    assert run["case_manifest_sha256"] == manifest_sha256(discover_case_dirs(fixture_cases))
    assert run["seed"] == 0
    assert run["case_count"] == len(CASE_IDS) == len(run["cases"])
    assert run["status_counts"] == {"completed": len(CASE_IDS)}
    assert run["tolerances"] == [0, 2, 5] and run["default_tolerance"] == 2
    assert run["reported_policy"] == "change_status == 'new'"
    assert "Semgrep " + tools["semgrep_version"] in run["arm_label"]
    # git may legitimately be unavailable; when it is available it must be a full SHA
    commit = run["git"]["commit"]
    assert commit is None or re.fullmatch(r"[0-9a-f]{40}", commit)


def test_the_seed_argument_is_recorded(tmp_path):
    case = write_case(tmp_path / "cases", document(ground_truth=[]))
    out = tmp_path / "out"
    proc = run_cli("--arm", "A", "--cases", str(case.parent), "--out", str(out), "--seed", "1234")
    assert proc.returncode == 0, proc.stderr
    assert load(out / "run.json")["seed"] == 1234


def _dict_keys(node):
    keys = set()
    if isinstance(node, dict):
        keys.update(node.keys())
        for value in node.values():
            keys |= _dict_keys(value)
    elif isinstance(node, list):
        for value in node:
            keys |= _dict_keys(value)
    return keys


def test_outputs_contain_no_timestamps_durations_or_absolute_paths(two_runs):
    _, _, out1, _ = two_runs
    time_like_key = re.compile(r"(time|date|duration|elapsed|created|latency|_at$)", re.I)
    iso_timestamp = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
    # JSON escapes backslashes, so compare against the escaped form of a Windows path
    leaked = [json.dumps(str(p))[1:-1] for p in (REPO_ROOT, out1)]
    for path in [out1 / "run.json", *[out1 / cid / "result.json" for cid in CASE_IDS]]:
        text = path.read_text(encoding="utf-8")
        offending = [k for k in _dict_keys(json.loads(text)) if time_like_key.search(k)]
        assert offending == [], (path.name, offending)
        assert not iso_timestamp.search(text), path.name
        assert not any(p in text for p in leaked), path.name
        assert "\r" not in text  # LF only, on every OS


def test_golden_result_for_new_finding_amid_existing_noise(two_runs):
    _, _, out1, _ = two_runs
    result = load(out1 / CASE_IDS[0] / "result.json")
    assert result["status"] == "completed" and result["arm"] == "A"
    findings = [
        (f["change_status"], f["source"], f["title"], f["start_line"]) for f in result["findings"]
    ]
    assert findings == [
        ("existing", "ESLINT", "no-unused-vars", 3),  # pre-existing: must not be reported
        ("new", "ESLINT", "no-unused-vars", 16),
        ("new", "SEMGREP", "eval-usage", 16),
    ]
    assert result["counts"]["reported"] == 2 and result["counts"]["existing"] == 1
    assert result["counts"]["ground_truth_defects"] == 2
    for k in ("0", "2", "5"):
        m = result["match"][k]
        # the eval on line 16 is found; the off-by-one on line 9 (a logic bug) is not
        assert m["detected_groups"] == ["#1"] and m["missed_groups"] == ["#0"]
        assert m["recall"] == 0.5
        assert m["unmatched_finding_indices"] == []


def test_golden_result_for_renamed_shifted_file_with_preexisting_issues(two_runs):
    _, _, out1, _ = two_runs
    result = load(out1 / CASE_IDS[1] / "result.json")
    assert result["status"] == "completed"
    assert [(f["change_status"], f["file_path"]) for f in result["findings"]] == [
        ("existing", "lib/reporting.js"),
        ("existing", "lib/reporting.js"),
    ]  # same identity across the rename and the shifted lines
    assert result["counts"]["reported"] == 0 and result["counts"]["ground_truth_defects"] == 0
    assert result["match"]["2"]["recall"] is None and result["match"]["2"]["precision"] is None


# ---- error handling (these fail before any tool runs, so they are quick) ----
def test_an_existing_run_is_not_overwritten_without_the_flag(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "run.json").write_text("{}", encoding="utf-8")
    proc = run_cli("--arm", "A", "--cases", str(COMMITTED_CASES), "--out", str(out))
    assert proc.returncode == 2
    assert "--overwrite" in proc.stderr
    assert (out / "run.json").read_text(encoding="utf-8") == "{}"


def test_arms_that_do_not_exist_are_refused_not_silently_substituted(tmp_path):
    for arm in ("B", "C", "D"):
        proc = run_cli("--arm", arm, "--cases", str(COMMITTED_CASES), "--out", str(tmp_path / arm))
        assert proc.returncode == 2
        assert not (tmp_path / arm).exists()


def test_a_malformed_case_aborts_the_whole_run_and_names_the_case(tmp_path):
    cases = tmp_path / "cases"
    write_case(cases, document(id="ok-1"))
    bad = document(id="bad-1")
    bad["ground_truth"][0]["end_line"] = 999
    write_case(cases, bad)
    proc = run_cli("--arm", "A", "--cases", str(cases), "--out", str(tmp_path / "out"))
    assert proc.returncode == 2
    assert "bad-1" in proc.stderr
    assert not (tmp_path / "out" / "run.json").exists()  # nothing half-written


def test_an_empty_cases_directory_is_an_error(tmp_path):
    (tmp_path / "cases").mkdir()
    proc = run_cli("--arm", "A", "--cases", str(tmp_path / "cases"), "--out", str(tmp_path / "out"))
    assert proc.returncode == 2 and "no cases found" in proc.stderr
