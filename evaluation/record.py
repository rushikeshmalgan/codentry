"""Builds the per-case `result.json` record: what the arm found, and how that
scores against the case's ground truth.

The record is a pure function of (case, arm result). It must stay byte-for-byte
reproducible, so it contains no timestamps, durations, absolute paths or
anything else that varies between runs — see evaluation/run.py for the run-level
`run.json`.
"""

from __future__ import annotations

from typing import Any

from analysis.diff import build_file_diff
from evaluation.case import Case, CaseInputs, line_count
from evaluation.metrics.matching import (
    TOLERANCES,
    Span,
    duplicate_count,
    match,
    ratio,
)
from evaluation.runners.arm_a_static import (
    ARM_ID,
    REPORTED_POLICY,
    ArmAResult,
    arm_label,
)

RESULT_SCHEMA = "codentry.eval.result/1"


def changed_line_count(inputs: CaseInputs) -> int:
    """Head lines the change added or modified (same offline diff the arm uses)."""
    total = 0
    for f in inputs.files:
        if f.head_content is None:
            continue
        diff = build_file_diff(None, f.base_content, f.head_content)
        limit = line_count(f.head_content)
        total += sum(1 for n in diff.added_lines if n <= limit)
    return total


def build_result(case: Case, result: ArmAResult) -> dict[str, Any]:
    findings = result.findings
    reported_positions = [i for i, f in enumerate(findings) if f.change_status == "new"]
    reported_spans = [
        Span(findings[i].file_path, findings[i].start_line, findings[i].end_line)
        for i in reported_positions
    ]
    defect_spans = [Span(d.file, d.start_line, d.end_line) for d in case.ground_truth]
    changed_lines = changed_line_count(case.inputs)
    reported_keys = [findings[i].identity_key or findings[i].dedup_hash for i in reported_positions]

    by_tolerance: dict[str, Any] = {}
    for k in TOLERANCES:
        m = match(reported_spans, defect_spans, k)
        tp = len(m.true_positive_findings)
        by_tolerance[str(k)] = {
            "tolerance": k,
            "defects": m.defects,
            "detected": len(m.detected_defects),
            "detected_defect_indices": list(m.detected_defects),
            "missed_defect_indices": list(m.missed_defects),
            "reported": m.reported,
            # indices into `findings` (not into the reported subset)
            "true_positive_finding_indices": [
                reported_positions[i] for i in m.true_positive_findings
            ],
            "false_positive_finding_indices": [
                reported_positions[i] for i in m.false_positive_findings
            ],
            "exactly_located": len(m.exactly_located_findings),
            "recall": ratio(len(m.detected_defects), m.defects),
            "precision": ratio(tp, m.reported),
            "location_accuracy": ratio(len(m.exactly_located_findings), tp),
        }

    counts = {status: 0 for status in ("new", "existing", "fixed", "unclassified")}
    for f in findings:
        counts[f.change_status or "unclassified"] += 1

    return {
        "schema": RESULT_SCHEMA,
        "arm": ARM_ID,
        "arm_label": arm_label(result.analysis_meta.get("head", {}).get("semgrep_version")),
        "case_id": case.id,
        "stratum": case.stratum,
        "status": result.status,
        "error_code": result.error_code,
        "reported_policy": REPORTED_POLICY,
        "counts": {
            **counts,
            "findings": len(findings),
            "reported": len(reported_positions),
            "reported_duplicates": duplicate_count(reported_keys),
            "changed_lines": changed_lines,
            "ground_truth_defects": len(case.ground_truth),
        },
        "findings_per_changed_line": ratio(len(reported_positions), changed_lines),
        "ground_truth": [
            {
                "file": d.file,
                "start_line": d.start_line,
                "end_line": d.end_line,
                "kind": d.kind,
                "provenance": d.provenance,
            }
            for d in case.ground_truth
        ],
        "match": by_tolerance,
        "findings": [f.model_dump(mode="json") for f in findings],
        "analysis_meta": result.analysis_meta,
    }
