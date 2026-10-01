"""The adjudication ("main") round: only UNMATCHED findings, everything up to 150,
calibration items excluded. Pure file handling; no tools."""

import json

import pytest

from evaluation.labeling import items
from evaluation.tests.test_labeling import fake_run


def with_match(results_dir, case_id, matched_indices, tolerance="2"):
    """Add a `match` block (as evaluation/record.py writes) to a fake result."""
    path = results_dir / case_id / "result.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    new = [i for i, f in enumerate(doc["findings"]) if f["change_status"] == "new"]
    doc["match"] = {
        tolerance: {
            "matched_finding_indices": sorted(matched_indices),
            "unmatched_finding_indices": [i for i in new if i not in matched_indices],
        }
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_matched_findings_are_never_adjudication_candidates(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 5})
    with_match(results, "case-a", matched_indices={0, 1})
    found = items.reported_findings(results, only_unmatched=True)
    assert [c["index"] for c in found] == [2, 3, 4]
    assert len(items.reported_findings(results)) == 5  # calibration behavior is unchanged


def test_every_finding_of_an_unlabeled_case_is_unmatched(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 4})
    with_match(results, "case-a", matched_indices=set())
    assert len(items.reported_findings(results, only_unmatched=True)) == 4


def test_the_tolerance_decides_what_counts_as_matched(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 3})
    with_match(results, "case-a", matched_indices={0}, tolerance="2")
    doc = json.loads((results / "case-a" / "result.json").read_text(encoding="utf-8"))
    doc["match"]["5"] = {"matched_finding_indices": [0, 1], "unmatched_finding_indices": [2]}
    (results / "case-a" / "result.json").write_text(json.dumps(doc), encoding="utf-8")
    assert len(items.reported_findings(results, only_unmatched=True, tolerance=2)) == 2
    assert len(items.reported_findings(results, only_unmatched=True, tolerance=5)) == 1


def test_all_unmatched_findings_are_used_when_there_are_150_or_fewer_with_no_case_cap(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 9, "case-b": 7})
    for case in ("case-a", "case-b"):
        with_match(results, case, matched_indices=set())
    chosen = items.build_items(results, cases, "main-01", None, seed=1,
                               only_unmatched=True, per_case_cap=None)
    assert len(chosen) == 16  # more than PER_CASE_CAP from one case: no cap in the main round
    assert sum(i["case_id"] == "case-a" for i in chosen) == 9
    assert [i["item_id"] for i in chosen][:2] == ["main-01-01", "main-01-02"]


def test_beyond_150_a_seeded_sample_of_150_is_drawn_and_it_is_reproducible(tmp_path):
    results, cases = fake_run(tmp_path, {f"case-{n:02d}": 20 for n in range(9)})  # 180 findings
    for n in range(9):
        with_match(results, f"case-{n:02d}", matched_indices=set())
    kwargs = {"only_unmatched": True, "per_case_cap": None}
    one = items.build_items(results, cases, "main-01", None, seed=7, **kwargs)
    two = items.build_items(results, cases, "main-01", None, seed=7, **kwargs)
    other = items.build_items(results, cases, "main-01", None, seed=8, **kwargs)
    assert len(one) == items.MAIN_ROUND_MAX == 150 and one == two and one != other
    assert one[0]["item_id"] == "main-01-001" and one[-1]["item_id"] == "main-01-150"  # 3-digit ids


def test_findings_already_used_for_calibration_are_excluded(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 6})
    with_match(results, "case-a", matched_indices=set())
    first = items.build_items(results, cases, "cal", 3, seed=1, only_unmatched=True)
    banned = frozenset(
        items.item_signature(i["case_id"], i["file"], i["start_line"], i["end_line"], i["rule"])
        for i in first
    )
    rest = items.build_items(results, cases, "main", None, seed=1, only_unmatched=True,
                             per_case_cap=None, exclude=banned)
    assert len(rest) == 3
    taken = {(i["start_line"]) for i in first}
    assert not taken & {i["start_line"] for i in rest}


def test_an_empty_main_round_is_an_error_not_an_empty_sheet(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 3})
    with_match(results, "case-a", matched_indices={0, 1, 2})
    with pytest.raises(items.ItemsError):
        items.build_items(results, cases, "main", None, seed=1, only_unmatched=True, per_case_cap=None)


def test_the_main_round_cli_writes_sheets_and_skips_calibration_items(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 8})
    with_match(results, "case-a", matched_indices=set())
    out = tmp_path / "labeling"
    cal = items.build_items(results, cases, "calibration-01", 3, seed=1, only_unmatched=True)
    items.write_round(out, "calibration-01", cal)
    code = items.main(["--results", str(results), "--cases", str(cases), "--round", "main-01",
                       "--seed", "5", "--out", str(out), "--main-round"])
    assert code == 0
    main_items = json.loads((out / "calibration" / "main-01.items.json").read_text(encoding="utf-8"))
    assert len(main_items) == 5  # 8 unmatched minus the 3 used for calibration
    assert not {i["start_line"] for i in cal} & {i["start_line"] for i in main_items}
    for who in ("a", "b"):
        rows = (out / "labels" / f"main-01.labeler-{who}.csv").read_text(encoding="utf-8").splitlines()
        assert rows[0] == "item_id,label,note" and len(rows) == 6
