"""The reproducibility script: it passes on an untouched run and fails when an input changes.

The report checks are tool-free. The re-run checks use the real tools on the two
fast hand-made fixtures only.
"""

import json
import shutil

import pytest

from evaluation import repro
from evaluation.metrics import report
from evaluation.run import run
from evaluation.tests.helpers import COMMITTED_CASES
from evaluation.tests.test_report import run_dir  # noqa: F401  (pytest fixture, reused)
from evaluation.tests.test_run_cli import CASE_IDS


# ---- report check (no tools) -----------------------------------------------------------
@pytest.fixture()
def stored_report(run_dir, tmp_path):  # noqa: F811
    agg = report.aggregate(run_dir)
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    md.write_bytes(report.render_markdown(agg).encode("utf-8"))
    js.write_bytes(report.render_json(agg).encode("utf-8"))
    return md, js


def test_an_untouched_report_reproduces(run_dir, stored_report, capsys):  # noqa: F811
    md, js = stored_report
    code = repro.main(["--run", str(run_dir), "--no-rerun", "--report-md", str(md), "--report-json", str(js)])
    assert code == 0 and "PASS report" in capsys.readouterr().out


def test_a_hand_edited_report_is_detected(run_dir, stored_report, capsys):  # noqa: F811
    md, js = stored_report
    md.write_bytes(md.read_bytes().replace(b"66.7%", b"99.9%", 1))
    code = repro.main(["--run", str(run_dir), "--no-rerun", "--report-md", str(md), "--report-json", str(js)])
    out = capsys.readouterr().out
    assert code == 1 and "FAIL report" in out and "r.md" in out


def test_a_changed_run_file_is_detected_through_the_report(run_dir, stored_report, capsys):  # noqa: F811
    md, js = stored_report
    path = run_dir / "l3" / "result.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["counts"]["reported"] = 5
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert repro.main(["--run", str(run_dir), "--no-rerun", "--report-md", str(md), "--report-json", str(js)]) == 1


def test_argument_errors_are_reported_not_ignored(run_dir):  # noqa: F811
    with pytest.raises(SystemExit):
        repro.main(["--run", str(run_dir)])  # neither --cases nor --no-rerun
    with pytest.raises(SystemExit):
        repro.main(["--run", str(run_dir), "--no-rerun"])  # nothing to check


def test_a_missing_run_is_exit_code_2(tmp_path, capsys):
    code = repro.main(["--run", str(tmp_path / "nope"), "--no-rerun", "--report-md", str(tmp_path / "a"),
                       "--report-json", str(tmp_path / "b")])
    assert code == 2


# ---- compare_runs (pure) -------------------------------------------------------------------
def record(**overrides):
    base = {
        "case_manifest_sha256": "m", "results_sha256": "r", "seed": 0,
        "tools": {"eslint_version": "8", "semgrep_version": "1", "ruleset_sha256": "x",
                  "baseline_config_sha256": "y"},
        "cases": [{"id": "a", "result_sha256": "1"}, {"id": "b", "result_sha256": "2"}],
    }
    base.update(overrides)
    return base


def test_identical_records_reproduce():
    assert repro.compare_runs(record(), record()) == []


def test_differences_are_named():
    changed = record(
        case_manifest_sha256="m2", results_sha256="r2",
        cases=[{"id": "a", "result_sha256": "1"}, {"id": "b", "result_sha256": "9"},
               {"id": "c", "result_sha256": "3"}],
        tools={"eslint_version": "9", "semgrep_version": "1", "ruleset_sha256": "x",
               "baseline_config_sha256": "y"},
    )
    problems = repro.compare_runs(record(), changed)
    text = "\n".join(problems)
    assert "case files differ" in text and "eslint_version differs" in text
    assert "case b: result changed" in text and "case c was not in the recorded run" in text
    assert "case a" not in text


# ---- re-running with the real tools (fixtures only) -------------------------------------
@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    base = tmp_path_factory.mktemp("repro")
    cases = base / "cases"
    for case_id in CASE_IDS:
        shutil.copytree(COMMITTED_CASES / case_id, cases / case_id)
    out = base / "recorded"
    run(cases, out, 0)
    return cases, out


def test_an_untouched_run_reproduces_with_the_real_tools(fixture_run, capsys):
    cases, out = fixture_run
    assert repro.main(["--run", str(out), "--cases", str(cases)]) == 0
    assert "PASS results" in capsys.readouterr().out


def test_changing_a_case_file_makes_the_rerun_fail_and_names_the_case(fixture_run, capsys):
    cases, out = fixture_run
    target = cases / CASE_IDS[0] / "head" / "src" / "tasks.js"
    original = target.read_bytes()
    try:
        target.write_bytes(original.replace(b"eval(expression)", b"(expression)"))
        code = repro.main(["--run", str(out), "--cases", str(cases)])
    finally:
        target.write_bytes(original)
    text = capsys.readouterr().out
    assert code == 1 and "FAIL results" in text
    assert "case files differ" in text and f"case {CASE_IDS[0]}: result changed" in text
