"""The optional --timing flag: it writes timing.json and nothing else changes.

Uses the real CLI as a subprocess, on the two fast hand-made fixtures only.
"""

import shutil

import pytest

from evaluation.tests.helpers import COMMITTED_CASES
from evaluation.tests.test_run_cli import CASE_IDS, load, run_cli


@pytest.fixture(scope="module")
def fixture_cases(tmp_path_factory):
    cases = tmp_path_factory.mktemp("timing-cases")
    for case_id in CASE_IDS:
        shutil.copytree(COMMITTED_CASES / case_id, cases / case_id)
    return cases


def test_timing_json_is_written_only_with_the_flag(tmp_path, fixture_cases):
    without = tmp_path / "without"
    proc = run_cli("--arm", "A", "--cases", str(fixture_cases), "--out", str(without))
    assert proc.returncode == 0, proc.stderr
    assert not (without / "timing.json").exists()

    with_timing = tmp_path / "with"
    proc = run_cli("--arm", "A", "--cases", str(fixture_cases), "--out", str(with_timing), "--timing")
    assert proc.returncode == 0, proc.stderr
    timing = load(with_timing / "timing.json")
    assert timing["schema"] == "codentry.eval.timing/1"
    assert set(timing["seconds_per_case"]) == set(CASE_IDS)
    assert all(v >= 0 for v in timing["seconds_per_case"].values())
    assert timing["total_seconds"] == pytest.approx(sum(timing["seconds_per_case"].values()))


def test_timing_never_changes_run_json_or_result_json_bytes(tmp_path, fixture_cases):
    without = tmp_path / "without"
    with_timing = tmp_path / "with"
    run_cli("--arm", "A", "--cases", str(fixture_cases), "--out", str(without))
    run_cli("--arm", "A", "--cases", str(fixture_cases), "--out", str(with_timing), "--timing")
    for relative in ["run.json", *[f"{cid}/result.json" for cid in CASE_IDS]]:
        assert (without / relative).read_bytes() == (with_timing / relative).read_bytes(), relative
