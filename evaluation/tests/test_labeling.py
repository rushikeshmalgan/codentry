"""Labeling tooling: item sampling, sheet rendering, label-file validation, agreement.
Pure file handling: no analysis tools, no network."""

import csv
import json
import random

import pytest
from jsonschema import Draft202012Validator

from evaluation.labeling import agreement, items
from evaluation.labeling.agreement import LabelError, compare, read_labels
from evaluation.tests.helpers import REPO_ROOT

LABELING = REPO_ROOT / "evaluation" / "labeling"
SCHEMA = json.loads((LABELING / "label.schema.json").read_bytes().decode("utf-8"))
ITEM_SCHEMA = {**SCHEMA, "oneOf": [{"$ref": "#/$defs/item"}]}
IDS = [f"r-{i:02d}" for i in range(1, 6)]


def write_csv(path, rows, header=("item_id", "label", "note")):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def full(labels):
    return [(i, label, "") for i, label in zip(IDS, labels, strict=True)]


# ---- reading and validating label files --------------------------------------
def test_a_complete_valid_label_file_is_read(tmp_path):
    path = write_csv(tmp_path / "a.csv", full(["real issue", "not an issue", "unclear", "real issue", "not an issue"]))
    labels = read_labels(path, IDS)
    assert labels["r-03"] == ("unclear", "") and len(labels) == 5


def test_notes_may_contain_commas_quotes_and_newlines(tmp_path):
    rows = full(["real issue"] * 5)
    rows[0] = ("r-01", "real issue", 'has a "quote", a comma\nand a newline')
    assert read_labels(write_csv(tmp_path / "a.csv", rows), IDS)["r-01"][1].startswith("has a")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda rows: rows.__setitem__(0, ("r-01", "", "")), "blank"),
        (lambda rows: rows.__setitem__(0, ("r-01", "maybe", "")), "maybe"),
        (lambda rows: rows.__setitem__(0, ("r-01", "Real Issue", "")), "Real Issue"),
        (lambda rows: rows.pop(), "missing labels for r-05"),
        (lambda rows: rows.append(("r-99", "unclear", "")), "unknown items r-99"),
        (lambda rows: rows.append(("r-01", "unclear", "")), "more than once"),
    ],
)
def test_invalid_label_files_are_refused_with_a_message_naming_the_problem(tmp_path, mutate, message):
    rows = full(["real issue"] * 5)
    mutate(rows)
    with pytest.raises(LabelError, match=message):
        read_labels(write_csv(tmp_path / "a.csv", rows), IDS)


def test_a_wrong_header_is_refused(tmp_path):
    path = write_csv(tmp_path / "a.csv", full(["real issue"] * 5), header=("id", "label", "note"))
    with pytest.raises(LabelError, match="header"):
        read_labels(path, IDS)


def test_a_byte_order_mark_and_blank_lines_are_tolerated(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes("﻿item_id,label,note\n".encode() + b"".join(
        f"{i},real issue,\n\n".encode() for i in IDS))
    assert len(read_labels(path, IDS)) == 5


# ---- agreement ----------------------------------------------------------------
def labels_of(values):
    return {i: (v, "") for i, v in zip(IDS, values, strict=True)}


def test_agreement_reports_observed_kappa_confusion_and_disagreements():
    a = labels_of(["real issue", "real issue", "not an issue", "not an issue", "unclear"])
    b = labels_of(["real issue", "not an issue", "not an issue", "not an issue", "not an issue"])
    result = compare(a, b, IDS)
    assert result.n == 5 and result.observed == pytest.approx(0.6)
    assert result.disagreements == ("r-02", "r-05")
    assert result.confusion[("real issue", "not an issue")] == 1
    assert result.kappa is not None and result.kappa < result.observed


def test_kappa_is_reported_again_with_unclear_merged_into_not_an_issue():
    a = labels_of(["real issue", "unclear", "unclear", "not an issue", "real issue"])
    b = labels_of(["real issue", "not an issue", "not an issue", "not an issue", "real issue"])
    result = compare(a, b, IDS)
    assert result.observed == pytest.approx(0.6)  # the two `unclear` items disagree
    assert result.kappa_unclear_as_not_an_issue == 1.0  # ... but agree once merged


def test_agreement_cli_refuses_invalid_input_and_computes_nothing(tmp_path, capsys):
    items_path = tmp_path / "r.items.json"
    items_path.write_text(json.dumps([{"item_id": i} for i in IDS]), encoding="utf-8")
    good = write_csv(tmp_path / "a.csv", full(["real issue"] * 5))
    bad_rows = full(["real issue"] * 5)
    bad_rows[4] = ("r-05", "", "")
    bad = write_csv(tmp_path / "b.csv", bad_rows)
    code = agreement.main(["--items", str(items_path), "--a", str(good), "--b", str(bad)])
    captured = capsys.readouterr()
    assert code == 2 and "error:" in captured.err and "kappa" not in captured.out.lower()


def test_agreement_cli_prints_the_figures_for_valid_files(tmp_path, capsys):
    items_path = tmp_path / "r.items.json"
    items_path.write_text(json.dumps([{"item_id": i} for i in IDS]), encoding="utf-8")
    a = write_csv(tmp_path / "a.csv", full(["real issue", "not an issue", "real issue", "unclear", "not an issue"]))
    b = write_csv(tmp_path / "b.csv", full(["real issue", "not an issue", "not an issue", "unclear", "not an issue"]))
    assert agreement.main(["--items", str(items_path), "--a", str(a), "--b", str(b)]) == 0
    out = capsys.readouterr().out
    assert "raw agreement: 0.800" in out and "disagreements to discuss: r-03" in out


# ---- building items ------------------------------------------------------------
def fake_run(tmp_path, per_case=None):
    """A results dir shaped like `evaluation.run` output, and matching case files."""
    per_case = per_case or {"case-a": 5, "case-b": 4, "case-c": 2}
    results, cases = tmp_path / "run", tmp_path / "cases"
    for case_id, count in per_case.items():
        source = "\n".join(f"line {n}" for n in range(1, 41)) + "\n"
        (cases / case_id / "head" / "src").mkdir(parents=True)
        (cases / case_id / "head" / "src" / "f.js").write_bytes(source.encode("utf-8"))
        findings = [
            {"source": "ESLINT", "title": "no-unused-vars", "file_path": "src/f.js",
             "start_line": 5 * (n + 1), "end_line": 5 * (n + 1), "description": f"message {n}",
             "identity_key": f"{case_id}-k{n}", "severity": "high", "change_status": "new"}
            for n in range(count)
        ] + [{"source": "ESLINT", "title": "old", "file_path": "src/f.js", "start_line": 1,
              "end_line": 1, "description": "existing", "identity_key": "e", "severity": "low",
              "change_status": "existing"}]
        (results / case_id).mkdir(parents=True)
        (results / case_id / "result.json").write_text(
            json.dumps({"case_id": case_id, "arm": "A", "findings": findings}), encoding="utf-8")
    return results, cases


def test_items_are_sampled_deterministically_and_only_from_reported_findings(tmp_path):
    results, cases = fake_run(tmp_path)
    one = items.build_items(results, cases, "cal-01", 6, seed=3)
    two = items.build_items(results, cases, "cal-01", 6, seed=3)
    assert one == two and len(one) == 6
    assert all(i["hidden"]["change_status"] == "new" for i in one)  # `existing` never sampled
    assert [i["item_id"] for i in one] == [f"cal-01-{n:02d}" for n in range(1, 7)]
    assert one != items.build_items(results, cases, "cal-01", 6, seed=4)


def test_no_case_supplies_more_than_the_cap(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 9, "case-b": 9})
    chosen = items.build_items(results, cases, "cal-01", 6, seed=1)
    counts = {c: sum(i["case_id"] == c for i in chosen) for c in ("case-a", "case-b")}
    assert max(counts.values()) <= items.PER_CASE_CAP


def test_too_few_findings_is_an_error_not_a_shorter_round(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 2})
    with pytest.raises(items.ItemsError, match="need 10"):
        items.build_items(results, cases, "cal-01", 10, seed=1)


def test_items_validate_against_the_schema_and_carry_code_context(tmp_path):
    results, cases = fake_run(tmp_path)
    validator = Draft202012Validator(ITEM_SCHEMA)
    for item in items.build_items(results, cases, "cal-01", 5, seed=1):
        assert list(validator.iter_errors(item)) == []
        ctx = item["context"]
        assert ctx["first_line"] <= item["start_line"] <= ctx["first_line"] + len(ctx["lines"])
        assert ctx["lines"][item["start_line"] - ctx["first_line"]] == f"line {item['start_line']}"


def test_the_sheet_shows_what_labelers_need_and_hides_what_could_bias_them(tmp_path):
    results, cases = fake_run(tmp_path)
    chosen = items.build_items(results, cases, "cal-01", 4, seed=1)
    sheet = items.render_sheet("cal-01", chosen)
    for item in chosen:
        assert item["item_id"] in sheet and item["message"] in sheet
        assert f"> {item['start_line']}" in sheet.replace("  ", " ")  # flagged line marked with >
    for hidden in ("identity_key", "severity", "change_status", "sampled_with_seed", "high", "-k"):
        assert hidden not in sheet, hidden
    assert "independently" in sheet


def test_blank_label_sheets_have_the_exact_header_and_every_item_once():
    chosen = [{"item_id": f"x-{n:02d}"} for n in range(1, 4)]
    rows = list(csv.reader(items.blank_label_csv(chosen).splitlines()))
    assert rows[0] == ["item_id", "label", "note"]
    assert [r[0] for r in rows[1:]] == ["x-01", "x-02", "x-03"] and all(r[1] == "" for r in rows[1:])


def test_a_blank_sheet_is_not_a_valid_label_file(tmp_path):
    """A template must be filled in: blank labels are refused, never counted or skipped."""
    path = tmp_path / "a.csv"
    path.write_text(items.blank_label_csv([{"item_id": i} for i in IDS]), encoding="utf-8")
    with pytest.raises(LabelError, match="blank"):
        read_labels(path, IDS)


def test_sampling_does_not_consume_global_randomness(tmp_path):
    results, cases = fake_run(tmp_path)
    random.seed(99)
    before = random.random()
    random.seed(99)
    items.build_items(results, cases, "cal-01", 5, seed=1)
    assert random.random() == before


# ---- the protocol document -----------------------------------------------------
def test_the_protocol_states_its_non_negotiable_rules():
    text = (LABELING / "protocol.md").read_text(encoding="utf-8")
    for required in ("Never a model", "Two independent labelers", "Blind to the arm",
                     "real issue", "not an issue", "unclear", "Cohen's κ", "calibration"):
        assert required in text, required


def test_findings_from_an_incomplete_analysis_are_never_sampled(tmp_path):
    results, cases = fake_run(tmp_path, {"case-a": 6, "case-b": 6})
    path = results / "case-b" / "result.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["status"] = "partial"
    path.write_text(json.dumps(doc), encoding="utf-8")
    chosen = items.build_items(results, cases, "cal-01", 3, seed=1)
    assert {i["case_id"] for i in chosen} == {"case-a"}


# ---- the committed calibration round ---------------------------------------------
CALIBRATION = LABELING / "calibration" / "calibration-01.items.json"


def committed_items():
    return json.loads(CALIBRATION.read_bytes().decode("utf-8"))


def test_the_committed_calibration_round_has_ten_valid_items_from_real_findings():
    chosen = committed_items()
    validator = Draft202012Validator(ITEM_SCHEMA)
    assert len(chosen) == 10
    assert [i["item_id"] for i in chosen] == [f"calibration-01-{n:02d}" for n in range(1, 11)]
    for item in chosen:
        assert list(validator.iter_errors(item)) == [], item["item_id"]
        assert item["hidden"]["change_status"] == "new" and item["hidden"]["arm"] == "A"
        case_dir = REPO_ROOT / "evaluation" / "cases" / item["case_id"]
        assert (case_dir / "head" / item["file"]).is_file(), item["item_id"]
    assert max(sum(i["case_id"] == c for i in chosen) for c in {i["case_id"] for i in chosen}) <= 3


def test_calibration_context_matches_the_committed_case_files():
    for item in committed_items():
        path = REPO_ROOT / "evaluation" / "cases" / item["case_id"] / "head" / item["file"]
        lines = path.read_bytes().decode("utf-8").split("\n")
        ctx = item["context"]
        assert lines[ctx["first_line"] - 1 : ctx["first_line"] - 1 + len(ctx["lines"])] == ctx["lines"]


@pytest.mark.parametrize("who", ["a", "b"])
def test_each_labeler_sheet_lists_every_item_once_with_only_legal_or_blank_labels(who):
    """Passes for a blank template AND for a sheet a labeler has since filled in."""
    ids = [i["item_id"] for i in committed_items()]
    path = LABELING / "labels" / f"calibration-01.labeler-{who}.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["item_id", "label", "note"]
    assert [r[0] for r in rows[1:]] == ids
    assert all(r[1] in ("", *agreement.LABELS) for r in rows[1:])


def test_the_sheet_does_not_leak_hidden_fields():
    sheet = (LABELING / "calibration" / "calibration-01.sheet.md").read_text(encoding="utf-8")
    for item in committed_items():
        assert item["hidden"]["identity_key"] not in sheet
        assert item["item_id"] in sheet
    for word in ("severity", "change_status", "identity_key", "existing"):
        assert word not in sheet


def test_the_label_files_are_pinned_against_line_ending_conversion():
    attributes = (LABELING / ".gitattributes").read_text(encoding="utf-8")
    assert "*.csv" in attributes and "-text" in attributes
