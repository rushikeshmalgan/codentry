"""Baseline performance measurement — a data point for Phase 7's real
measurements, not a promise about production latency. Prints timings so
they show up in `pytest -s` output; asserts only a generous upper bound to
catch a genuine hang/regression, not to make a speed claim.
"""

import time
from pathlib import Path

from analysis.eslint_runner import run_eslint
from analysis.semgrep_runner import run_semgrep
from analysis.static_analysis import run_static_analysis
from analysis.workspace import SourceFile, materialize

FIXTURES = Path(__file__).parent.parent / "analysis" / "fixtures"

# A generous multi-file synthetic diff: 20 files, each a copy of the ESLint
# fixture, to approximate a "large PR" without depending on network access
# to fetch a real one.
_LARGE_FILE_COUNT = 20


def _large_file_set() -> list[SourceFile]:
    template = (FIXTURES / "eslint_sample.js").read_text()
    return [SourceFile(path=f"src/file_{i}.js", content=template) for i in range(_LARGE_FILE_COUNT)]


def test_performance_baseline_on_a_larger_synthetic_diff(capsys):
    files = _large_file_set()
    relative_paths = [f.path for f in files]

    with materialize(files) as workspace:
        eslint_start = time.monotonic()
        eslint_result = run_eslint(workspace, relative_paths)
        eslint_seconds = time.monotonic() - eslint_start

        semgrep_start = time.monotonic()
        semgrep_result = run_semgrep(workspace, relative_paths)
        semgrep_seconds = time.monotonic() - semgrep_start

    total_findings = sum(len(r["messages"]) for r in eslint_result.file_reports) + len(semgrep_result.results)

    with capsys.disabled():
        print(
            f"\n[perf baseline] files={_LARGE_FILE_COUNT} "
            f"eslint={eslint_seconds:.2f}s semgrep={semgrep_seconds:.2f}s "
            f"total_findings={total_findings}"
        )

    assert eslint_result.status == "ok"
    assert semgrep_result.status == "ok"
    # Generous bound: catches a genuine hang/regression, not a speed claim.
    # Phase 7 measures real-PR latency on real infrastructure; this is a dev-box sanity check only.
    assert eslint_seconds < 25
    assert semgrep_seconds < 25


def test_performance_baseline_end_to_end_via_run_static_analysis(tmp_path, capsys):
    files = _large_file_set()
    for f in files:
        target = tmp_path / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content)

    start = time.monotonic()
    result = run_static_analysis(str(tmp_path), [f.path for f in files])
    elapsed = time.monotonic() - start

    with capsys.disabled():
        print(f"\n[perf baseline] end-to-end run_static_analysis: {elapsed:.2f}s, {len(result.findings)} findings")

    assert result.overall_status == "completed"
    assert elapsed < 45
