"""Arm C: the overlap/independence arithmetic, pure and on synthetic two-arm results.

No tools, no network. Arm B does not exist in this repository, so the CLI's two-arm
path is exercised here against hand-built result.json shapes, not a real second arm.
"""

import json

import pytest

from evaluation.metrics.stats import mcnemar_exact
from evaluation.runners import arm_c_union as c


def defect(group):
    return {"group": group}


def result(case_id, stratum, groups, detected, *, status="completed", labeled=True, unmatched=0):
    """`groups`: every defect group in the case. `detected`: the subset this arm found."""
    return {
        "case_id": case_id,
        "stratum": stratum,
        "status": status,
        "ground_truth_status": "labeled" if labeled else "unlabeled",
        "ground_truth": [defect(g) for g in groups],
        "match": {"2": {"detected_groups": sorted(detected), "unmatched_finding_indices": list(range(unmatched))}},
    }


# ---- phi coefficient ---------------------------------------------------------------
def test_phi_is_one_for_perfectly_aligned_indicators():
    assert c.phi_coefficient([True, True, False, False], [True, True, False, False]) == pytest.approx(1.0)


def test_phi_is_minus_one_for_perfectly_opposed_indicators():
    assert c.phi_coefficient([True, True, False, False], [False, False, True, True]) == pytest.approx(-1.0)


def test_phi_is_none_when_one_side_never_varies():
    assert c.phi_coefficient([True, True, True], [True, False, True]) is None
    assert c.phi_coefficient([], []) is None


def test_phi_is_near_zero_for_independent_looking_data():
    a = [True, False, True, False, True, False, True, False]
    b = [True, True, False, False, True, True, False, False]
    assert abs(c.phi_coefficient(a, b)) < 0.5  # not a strict independence proof, just a sanity bound


# ---- compare(): overlap, recall, mcnemar ------------------------------------------
def test_overlap_counts_and_recall_on_a_hand_worked_stratum():
    # 4 cases, one defect group each: both detect c1; only A detects c2; only B detects c3; neither detects c4
    a = {
        "c1": result("c1", "s", ["g"], {"g"}),
        "c2": result("c2", "s", ["g"], {"g"}),
        "c3": result("c3", "s", ["g"], set()),
        "c4": result("c4", "s", ["g"], set()),
    }
    b = {
        "c1": result("c1", "s", ["g"], {"g"}),
        "c2": result("c2", "s", ["g"], set()),
        "c3": result("c3", "s", ["g"], {"g"}),
        "c4": result("c4", "s", ["g"], set()),
    }
    out = c.compare(a, b)["strata"]["s"]
    assert out["overlap"] == {"only_a": 1, "only_b": 1, "both": 1, "neither": 1}
    assert out["defect_groups"] == 4
    assert (out["recall_a"]["successes"], out["recall_a"]["n"]) == (2, 4)
    assert (out["recall_b"]["successes"], out["recall_b"]["n"]) == (2, 4)
    assert (out["recall_union"]["successes"], out["recall_union"]["n"]) == (3, 4)  # c4 still missed by both
    assert out["mcnemar_p_value"] == mcnemar_exact(1, 1)


def test_mcnemar_reflects_a_lopsided_discordant_split():
    cases = {f"c{i}": None for i in range(10)}
    a_detects = set(range(8))   # A gets 8 of 10
    b_detects = {0, 1}          # B gets only 2, both also gotten by A -> 6 only_a, 0 only_b
    a = {cid: result(cid, "s", ["g"], {"g"} if i in a_detects else set()) for i, cid in enumerate(cases)}
    b = {cid: result(cid, "s", ["g"], {"g"} if i in b_detects else set()) for i, cid in enumerate(cases)}
    out = c.compare(a, b)["strata"]["s"]
    assert out["overlap"] == {"only_a": 6, "only_b": 0, "both": 2, "neither": 2}
    assert out["mcnemar_p_value"] == mcnemar_exact(6, 0)
    assert out["mcnemar_p_value"] < 0.05  # A is significantly better here, by construction


def test_group_ids_are_scoped_to_the_case_not_global():
    """Two different cases both using the case-local group id '#0' must not be conflated."""
    a = {
        "m1": result("m1", "mutant:logic", ["#0"], {"#0"}),
        "m2": result("m2", "mutant:logic", ["#0"], set()),
    }
    b = {
        "m1": result("m1", "mutant:logic", ["#0"], set()),
        "m2": result("m2", "mutant:logic", ["#0"], {"#0"}),
    }
    out = c.compare(a, b)["strata"]["mutant:logic"]
    assert out["overlap"] == {"only_a": 1, "only_b": 1, "both": 0, "neither": 0}


def test_unlabeled_strata_are_skipped_entirely():
    a = {"n1": result("n1", "noise:pr", [], set(), labeled=False)}
    b = {"n1": result("n1", "noise:pr", [], set(), labeled=False)}
    assert c.compare(a, b)["strata"] == {}


def test_incomplete_cases_are_excluded_from_every_number_in_that_stratum():
    a = {
        "c1": result("c1", "s", ["g"], {"g"}),
        "c2": result("c2", "s", ["g"], {"g"}, status="partial"),
    }
    b = {
        "c1": result("c1", "s", ["g"], {"g"}),
        "c2": result("c2", "s", ["g"], set()),
    }
    out = c.compare(a, b)["strata"]["s"]
    assert out["excluded_incomplete"] == ["c2"] and out["completed_by_both_arms"] == 1
    assert out["defect_groups"] == 1  # c2's defect group is not counted either


def test_strata_pool_separately_never_together():
    a = {
        "m1": result("m1", "mutant:logic", ["#0"], {"#0"}),
        "r1": result("r1", "mutant:rule-aligned", ["#0"], set()),
    }
    b = {
        "m1": result("m1", "mutant:logic", ["#0"], {"#0"}),
        "r1": result("r1", "mutant:rule-aligned", ["#0"], {"#0"}),
    }
    out = c.compare(a, b)["strata"]
    assert set(out) == {"mutant:logic", "mutant:rule-aligned"}
    assert out["mutant:logic"]["overlap"]["both"] == 1
    assert out["mutant:rule-aligned"]["overlap"]["only_b"] == 1


def test_unmatched_per_case_pools_both_arms_and_is_never_called_false_positive():
    a = {"c1": result("c1", "s", ["g"], {"g"}, unmatched=2)}
    b = {"c1": result("c1", "s", ["g"], {"g"}, unmatched=1)}
    out = c.compare(a, b)["strata"]["s"]["unmatched_per_case"]
    assert out == {"arm_a": 2.0, "arm_b": 1.0, "union": 3.0}
    assert "false_positive" not in json.dumps(c.compare(a, b))


def test_mismatched_case_sets_are_refused():
    a = {"c1": result("c1", "s", ["g"], {"g"})}
    b = {"c2": result("c2", "s", ["g"], {"g"})}
    with pytest.raises(c.ArmCError, match="same cases"):
        c.compare(a, b)


# ---- the plan (Arm B does not exist) -----------------------------------------------
def test_the_plan_names_every_metric_and_does_not_fabricate_results():
    p = c.plan()
    assert p["schema"] == c.SCHEMA_PLAN and p["status"] == "arm_b_does_not_exist"
    assert len(p["would_compute"]) >= 5
    assert "strata" not in p  # describes metrics; computes none


# ---- CLI ----------------------------------------------------------------------------
def write_run(tmp_path, name, case_manifest_sha, results):
    out = tmp_path / name
    for cid, r in results.items():
        (out / cid).mkdir(parents=True)
        (out / cid / "result.json").write_text(json.dumps(r), encoding="utf-8")
    (out / "run.json").write_text(json.dumps({
        "case_manifest_sha256": case_manifest_sha,
        "cases": [{"id": cid} for cid in results],
    }), encoding="utf-8")
    return out


def test_cli_without_arm_b_writes_the_plan(tmp_path, capsys):
    run_a = write_run(tmp_path, "a", "h1", {"c1": result("c1", "s", ["g"], {"g"})})
    out = tmp_path / "out.json"
    assert c.main(["--arm-a-run", str(run_a), "--out", str(out)]) == 0
    assert json.loads(out.read_bytes())["schema"] == c.SCHEMA_PLAN
    assert "plan only" in capsys.readouterr().out


def test_cli_refuses_runs_over_different_case_sets(tmp_path, capsys):
    run_a = write_run(tmp_path, "a", "h1", {"c1": result("c1", "s", ["g"], {"g"})})
    run_b = write_run(tmp_path, "b", "h2", {"c1": result("c1", "s", ["g"], {"g"})})
    code = c.main(["--arm-a-run", str(run_a), "--arm-b-run", str(run_b), "--out", str(tmp_path / "o.json")])
    assert code == 2 and "different case sets" in capsys.readouterr().err


def test_cli_with_two_matching_runs_writes_the_comparison(tmp_path, capsys):
    results_a = {"c1": result("c1", "s", ["g"], {"g"})}
    results_b = {"c1": result("c1", "s", ["g"], set())}
    run_a = write_run(tmp_path, "a", "same-hash", results_a)
    run_b = write_run(tmp_path, "b", "same-hash", results_b)
    out = tmp_path / "o.json"
    assert c.main(["--arm-a-run", str(run_a), "--arm-b-run", str(run_b), "--out", str(out)]) == 0
    record = json.loads(out.read_bytes())
    assert record["schema"] == c.SCHEMA_RESULT
    assert record["strata"]["s"]["overlap"] == {"only_a": 1, "only_b": 0, "both": 0, "neither": 0}
    assert "mcnemar p=" in capsys.readouterr().out
