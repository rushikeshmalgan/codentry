"""Report generation on a tiny synthetic run whose numbers can be checked by hand.

No analysis tools run here: the report is a pure function of run files on disk.
"""

import json
import os
import re
from pathlib import Path

import pytest

from evaluation.metrics import report
from evaluation.metrics.stats import wilson_interval

GOLDEN = Path(__file__).parent / "golden" / "report-fixture.md"


def match_block(detected, defects, matched, unmatched, exact):
    return {
        "detected": detected,
        "defects": defects,
        "matched_finding_indices": list(range(matched)),
        "unmatched_finding_indices": list(range(matched, matched + unmatched)),
        "exactly_located": exact,
    }


def result(case_id, stratum, *, status="completed", labeled=True, reported=0, existing=0,
           changed=10, dups=0, k0=(0, 1, 0, 0, 0), k2=(0, 1, 0, 0, 0), k5=(0, 1, 0, 0, 0)):
    return {
        "case_id": case_id,
        "stratum": stratum,
        "status": status,
        "ground_truth_status": "labeled" if labeled else "unlabeled",
        "counts": {
            "new": reported, "existing": existing, "fixed": 0, "unclassified": 0,
            "reported": reported, "reported_duplicates": dups, "changed_lines": changed,
            "findings": reported + existing,
        },
        "match": {"0": match_block(*k0), "2": match_block(*k2), "5": match_block(*k5)},
    }


FIXTURE_RESULTS = [
    # mutant:logic — recall k0 1/3, k2 2/3, k5 2/3; the 4th case is partial and must be excluded
    result("l1", "mutant:logic", reported=2, changed=10, k0=(1, 1, 1, 1, 1), k2=(1, 1, 1, 1, 1), k5=(1, 1, 1, 1, 1)),
    result("l2", "mutant:logic", reported=1, changed=5, k2=(1, 1, 1, 0, 0), k5=(1, 1, 1, 0, 0),
           k0=(0, 1, 0, 1, 0)),
    result("l3", "mutant:logic", reported=0, changed=8),
    result("l4", "mutant:logic", status="partial", reported=3, changed=12, dups=1),
    # mutant:rule-aligned — everything detected
    result("r1", "mutant:rule-aligned", reported=1, k0=(1, 1, 1, 0, 1), k2=(1, 1, 1, 0, 1), k5=(1, 1, 1, 0, 1)),
    result("r2", "mutant:rule-aligned", reported=1, k0=(1, 1, 1, 0, 1), k2=(1, 1, 1, 0, 1), k5=(1, 1, 1, 0, 1)),
    # real:bugsjs
    result("b1", "real:bugsjs", reported=1, changed=20, k2=(1, 1, 1, 0, 1), k5=(1, 1, 1, 0, 1), k0=(1, 1, 1, 0, 1)),
    result("b2", "real:bugsjs", reported=0, changed=20),
    # noise:pr — unlabeled: findings volume only
    result("n1", "noise:pr", labeled=False, reported=4, existing=2, changed=40, dups=1),
    result("n2", "noise:pr", labeled=False, reported=0, existing=6, changed=60),
    # fixture — excluded from evidence
    result("fx-1", "fixture:new-and-existing", reported=2),
]


@pytest.fixture()
def run_dir(tmp_path):
    out = tmp_path / "run"
    for r in FIXTURE_RESULTS:
        (out / r["case_id"]).mkdir(parents=True)
        (out / r["case_id"] / "result.json").write_text(json.dumps(r), encoding="utf-8")
    statuses = {}
    for r in FIXTURE_RESULTS:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    (out / "run.json").write_text(json.dumps({
        "arm": "A", "arm_label": "ESLint + Codentry baseline ruleset (6 rules) run with Semgrep 9.9.9",
        "reported_policy": "change_status == 'new'", "default_tolerance": 2,
        "git": {"commit": "a" * 40, "dirty": False},
        "case_manifest_sha256": "b" * 64, "results_sha256": "c" * 64,
        "tools": {"eslint_version": "8.0.0", "semgrep_version": "9.9.9", "node_version": "v22.0.0",
                  "python_version": "3.13.0", "ruleset_sha256": "d" * 64},
        "case_count": len(FIXTURE_RESULTS), "status_counts": statuses,
        "cases": [{"id": r["case_id"]} for r in FIXTURE_RESULTS],
    }), encoding="utf-8")
    (out / "timing.json").write_text(json.dumps({
        "schema": "codentry.eval.timing/1", "total_seconds": 0,
        "seconds_per_case": {r["case_id"]: 1.0 + i for i, r in enumerate(FIXTURE_RESULTS)},
    }), encoding="utf-8")
    return out


# ---- arithmetic, checked by hand -----------------------------------------------------
def test_recall_counts_pool_defects_within_a_stratum_and_carry_a_wilson_interval(run_dir):
    logic = report.aggregate(run_dir)["strata"]["mutant:logic"]
    assert [(logic["recall"][k]["successes"], logic["recall"][k]["n"]) for k in ("0", "2", "5")] == [
        (1, 3), (2, 3), (2, 3)
    ]
    assert logic["recall"]["2"]["wilson95"] == list(wilson_interval(2, 3))
    assert logic["recall"]["2"]["value"] == pytest.approx(2 / 3)


def test_incomplete_cases_are_excluded_from_metrics_and_listed(run_dir):
    logic = report.aggregate(run_dir)["strata"]["mutant:logic"]
    assert logic["cases"] == 4 and logic["completed"] == 3
    assert logic["excluded_incomplete"] == ["l4"]
    assert logic["reported"]["total"] == 3  # l4's 3 findings are not counted
    assert logic["duplicates"]["n"] == 3 and logic["duplicates"]["successes"] == 0  # l4's duplicate excluded


def test_location_accuracy_is_exact_over_matched_and_unmatched_is_not_called_false(run_dir):
    logic = report.aggregate(run_dir)["strata"]["mutant:logic"]
    assert (logic["location_accuracy"]["successes"], logic["location_accuracy"]["n"]) == (1, 2)
    assert logic["matched_findings"] == 2 and logic["unmatched_findings"] == 1
    assert "false_positive" not in json.dumps(report.aggregate(run_dir))


def test_findings_per_case_and_per_changed_line(run_dir):
    rep = report.aggregate(run_dir)["strata"]["mutant:logic"]["reported"]
    assert rep["mean_per_case"] == pytest.approx(1.0) and rep["median_per_case"] == 1
    assert rep["max_per_case"] == 2 and rep["changed_lines"] == 23
    assert rep["per_100_changed_lines"] == pytest.approx(100 * 3 / 23)
    low, high = rep["mean_per_case_bootstrap95"]
    assert low <= 1.0 <= high


def test_the_bootstrap_interval_is_reproducible(run_dir):
    a = report.aggregate(run_dir)["strata"]["mutant:logic"]["reported"]["mean_per_case_bootstrap95"]
    b = report.aggregate(run_dir)["strata"]["mutant:logic"]["reported"]["mean_per_case_bootstrap95"]
    assert a == b


def test_unlabeled_strata_report_volume_and_share_but_never_recall_or_precision(run_dir):
    noise = report.aggregate(run_dir)["strata"]["noise:pr"]
    assert noise["kind"] == "unlabeled" and "recall" not in noise and "location_accuracy" not in noise
    assert noise["reported"]["total"] == 4 and noise["reported"]["mean_per_case"] == 2.0
    assert (noise["existing_share"]["successes"], noise["existing_share"]["n"]) == (8, 12)
    assert (noise["duplicates"]["successes"], noise["duplicates"]["n"]) == (1, 4)


def test_strata_are_never_pooled_and_fixtures_are_not_measured(run_dir):
    agg = report.aggregate(run_dir)
    assert set(agg["strata"]) == {
        "mutant:logic", "mutant:rule-aligned", "real:bugsjs", "noise:pr", "fixture:new-and-existing"
    }
    assert agg["strata"]["mutant:rule-aligned"]["recall"]["2"]["successes"] == 2
    fixture = agg["strata"]["fixture:new-and-existing"]
    assert fixture["kind"] == "fixture" and "reported" not in fixture and "recall" not in fixture
    assert "overall" not in json.dumps(agg).lower()


def test_latency_is_summarized_over_completed_cases_when_timing_exists(run_dir):
    lat = report.aggregate(run_dir)["strata"]["mutant:logic"]["latency_seconds"]
    assert lat["n"] == 3 and lat["median"] == 2.0 and lat["max"] == 3.0  # l1..l3 = 1.0, 2.0, 3.0
    (run_dir / "timing.json").unlink()
    assert "latency_seconds" not in report.aggregate(run_dir)["strata"]["mutant:logic"]


# ---- the rendered report ---------------------------------------------------------------
def test_every_proportion_is_printed_with_its_interval(run_dir):
    text = report.render_markdown(report.aggregate(run_dir))
    found = re.findall(r"\d+/\d+ = [\d.]+%", text)
    assert found, "expected proportions"
    for match in re.finditer(r"\d+/\d+ = [\d.]+%", text):
        assert text[match.end():].startswith(" (95% CI"), match.group(0)


def test_the_limitations_block_and_the_not_measured_section_are_present(run_dir):
    agg = report.aggregate(run_dir)
    text = report.render_markdown(agg)
    assert "## Limitations" in text and "## Not measured" in text
    for limitation in report.LIMITATIONS:
        assert limitation in text
    assert agg["adjudication"]["status"] == "not_done"
    assert "not estimated" in text.lower()


def test_the_report_lists_the_cases_behind_every_number(run_dir):
    text = report.render_markdown(report.aggregate(run_dir))
    section = text.split("## Case lists")[1]
    for r in FIXTURE_RESULTS:
        assert f"`{r['case_id']}`" in section


def test_the_report_contains_no_timestamp_or_absolute_path(run_dir):
    text = report.render_markdown(report.aggregate(run_dir)) + report.render_json(report.aggregate(run_dir))
    assert str(run_dir) not in text and str(run_dir).replace("\\", "\\\\") not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)


def test_regenerating_from_the_same_run_is_byte_identical(run_dir, tmp_path):
    for name in ("first", "second"):
        assert report.main(["--run", str(run_dir), "--out-dir", str(tmp_path / name), "--name", "r"]) == 0
    for suffix in ("md", "json"):
        assert (tmp_path / "first" / f"r.{suffix}").read_bytes() == (tmp_path / "second" / f"r.{suffix}").read_bytes()


def test_a_changed_input_changes_the_report(run_dir):
    before = report.render_markdown(report.aggregate(run_dir))
    path = run_dir / "l3" / "result.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["match"]["2"] = match_block(1, 1, 1, 0, 1)
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert report.render_markdown(report.aggregate(run_dir)) != before


def test_identity_stability_results_are_included_when_given(run_dir, tmp_path):
    stability = tmp_path / "stab.json"
    stability.write_text(json.dumps({
        "schema": "codentry.eval.identity_stability/1", "files_examined": 5, "files_with_findings": 3,
        "findings_before": 10,
        "transforms": {
            "line_shift": {"before": 10, "after": 10, "stable": 10, "vanished": 0, "appeared": 0},
            "trailing_whitespace": {"before": 10, "after": 9, "stable": 9, "vanished": 1, "appeared": 0},
        },
    }), encoding="utf-8")
    text = report.render_markdown(report.aggregate(run_dir, stability))
    assert "10/10 = 100.0% (95% CI" in text and "9/10 = 90.0% (95% CI" in text
    assert "vanished" in text


def test_the_rendered_report_matches_the_golden_file(run_dir):
    text = report.render_markdown(report.aggregate(run_dir))
    if os.environ.get("REGENERATE_GOLDEN") == "1":  # explicit, reviewed opt-in only
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(text.encode("utf-8"))
    assert text == GOLDEN.read_text(encoding="utf-8"), (
        "report format changed; if intended, regenerate evaluation/tests/golden/report-fixture.md"
    )
