"""Scoring records: unlabeled cases, group-level recall, unmatched (not 'false positive')
findings. Pure: findings are constructed directly, no analysis tools run."""

import pytest

from analysis.finding import Finding
from evaluation.case import Case, CaseFile, CaseInputs, Defect
from evaluation.record import build_result
from evaluation.runners.arm_a_static import ArmAResult


def finding(line: int, end: int | None = None, path: str = "a.js", status: str = "new") -> Finding:
    return Finding(
        source="ESLINT", category="correctness", severity="medium", title="rule",
        description="d", file_path=path, start_line=line, end_line=end or line,
        identity_key=f"k{path}{line}", dedup_hash=f"h{path}{line}", change_status=status,
    )


def defect(start: int, end: int | None = None, group: str = "#0") -> Defect:
    return Defect("a.js", start, end or start, "correctness", "real_defect",
                  (("dataset_annotation", "x"),), group)


def make_case(defects, status="labeled") -> Case:
    file = CaseFile("a.js", "modified", None, "x\n" * 60, "y\n" * 60)
    inputs = CaseInputs("c", "javascript", "n/a", "n/a", (file,))
    return Case("c", "test:unit", inputs, tuple(defects), status)


def result(*findings) -> ArmAResult:
    return ArmAResult("completed", None, list(findings), {"head": {"semgrep_version": "0"}})


def at(record, k=2):
    return record["match"][str(k)]


def test_a_labeled_case_scores_recall_precision_and_location():
    record = build_result(make_case([defect(10)]), result(finding(10), finding(40)))
    m = at(record)
    assert (m["defects"], m["detected"], m["recall"]) == (1, 1, 1.0)
    assert m["precision"] == 0.5 and m["location_accuracy"] == 1.0
    assert record["ground_truth_status"] == "labeled"


def test_unmatched_findings_are_reported_as_unmatched_never_as_false_positives():
    record = build_result(make_case([defect(10)]), result(finding(10), finding(40)))
    m = at(record)
    assert m["unmatched_finding_indices"] == [1] and m["matched_finding_indices"] == [0]
    assert not any("false_positive" in key for key in m)


@pytest.mark.parametrize("k", [0, 2, 5])
def test_an_unlabeled_case_has_no_recall_precision_or_location_accuracy(k):
    """No labels means these are undefined, not zero and not one."""
    record = build_result(make_case([], "unlabeled"), result(finding(10), finding(11)))
    m = at(record, k)
    assert (m["recall"], m["precision"], m["location_accuracy"]) == (None, None, None)
    assert m["reported"] == 2 and record["counts"]["reported"] == 2  # volume is still measured
    assert record["ground_truth_status"] == "unlabeled"


def test_locations_of_one_defect_are_one_defect_and_recall_counts_the_group_once():
    """A bug fixed in two hunks is one defect: hitting either location detects it."""
    defects = [defect(10, group="bug1"), defect(50, group="bug1"), defect(30, group="bug2")]
    record = build_result(make_case(defects), result(finding(50)))
    m = at(record, 0)
    assert m["defects"] == 2 and m["locations"] == 3
    assert m["detected_groups"] == ["bug1"] and m["missed_groups"] == ["bug2"]
    assert m["recall"] == 0.5
    assert record["counts"]["ground_truth_defects"] == 2
    assert record["counts"]["ground_truth_locations"] == 3


def test_hitting_every_location_of_a_group_does_not_count_it_twice():
    defects = [defect(10, group="bug1"), defect(50, group="bug1")]
    record = build_result(make_case(defects), result(finding(10), finding(50)))
    m = at(record, 0)
    assert (m["defects"], m["detected"], m["recall"]) == (1, 1, 1.0)


def test_only_new_findings_are_reported():
    record = build_result(
        make_case([defect(10)]),
        result(finding(10, status="existing"), finding(12, status="fixed")),
    )
    m = at(record)
    assert m["reported"] == 0 and m["detected"] == 0 and m["recall"] == 0.0
    assert m["precision"] is None  # nothing reported: undefined, not 0 or 1


def test_result_schema_version_reflects_the_new_fields():
    assert build_result(make_case([], "unlabeled"), result())["schema"].endswith("/2")
