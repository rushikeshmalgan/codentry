"""Differential analysis of one pull-request snapshot — pure: no store, no
network, no clock. Directly testable, and shared by two callers so that both
run *exactly* the same code:

- `app/review_runner.py` (the worker, after fetching a pinned GitHub snapshot)
- `evaluation/` (the research harness, over cases read from disk)

Keeping one implementation matters for the research claim: an evaluation of
"what Codentry's static arm finds" is only meaningful if it runs the code path
production runs, not a copy that can drift.

Both sides are analyzed with identical tools and the same trusted config
(never the PR's own); findings are then classified new / existing / fixed.
"""

from __future__ import annotations

from typing import Any

from analysis.changed_files import PullRequestSnapshot
from analysis.diff import FileDiff, build_file_diff
from analysis.differential import classify
from analysis.finding import Finding
from analysis.redact import redact_secrets
from analysis.static_analysis import analyze_source_files
from analysis.trusted_config import TRUSTED_CONFIG_FILENAME, sanitize_overlay
from analysis.workspace import is_incomplete_skip


class AnalysisOutcome:
    def __init__(
        self,
        status: str,
        findings: list[Finding],
        meta: dict[str, Any],
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        self.status = status
        self.findings = findings
        self.meta = meta
        self.error_code = error_code
        self.error_message = error_message


def _tool_ok(status: str) -> bool:
    return status in ("ok", "skipped")


def analyze_pull_request_snapshot(snapshot: PullRequestSnapshot, scope: str) -> AnalysisOutcome:
    """`scope` namespaces finding identities (the app passes the repository id)."""
    overlay = None
    if snapshot.trusted_config_text is not None:
        overlay = sanitize_overlay(
            snapshot.trusted_config_text,
            source_ref=f"{snapshot.base_sha}:{TRUSTED_CONFIG_FILENAME}",
        )
    rename_map = snapshot.rename_map

    head_result = analyze_source_files(snapshot.head_files, overlay, scope)
    base_result = analyze_source_files(snapshot.base_files, overlay, scope, rename_map)

    diffs: dict[str, FileDiff] = {
        f.path: build_file_diff(
            f.patch, f.base.content if f.base else None, f.head.content if f.head else None
        )
        for f in snapshot.files
    }

    # Which head findings can be honestly classified against the base?
    # A tool that failed on the base, or a file whose old content could not be
    # read, gives no basis for "new vs pre-existing" — those stay unclassified
    # (change_status=None) and are never treated as new.
    base_ok_sources = set()
    if _tool_ok(base_result.eslint_status):
        base_ok_sources.add("ESLINT")
    if _tool_ok(base_result.semgrep_status):
        base_ok_sources.add("SEMGREP")
    base_unavailable_paths = {f.path for f in snapshot.files if f.base_unavailable}
    for entry in base_result.skipped_files:
        if not is_incomplete_skip(entry):
            continue
        if entry["path"] == "*":  # base findings were truncated: no reliable baseline at all
            base_ok_sources.clear()
        else:
            base_unavailable_paths.add(rename_map.get(entry["path"], entry["path"]))

    classifiable_head: list[Finding] = []
    unclassified: list[Finding] = []
    for finding in head_result.findings:
        if finding.source in base_ok_sources and finding.file_path not in base_unavailable_paths:
            classifiable_head.append(finding)
        else:
            unclassified.append(finding)

    classifiable_base = [f for f in base_result.findings if f.source in base_ok_sources]
    differential = classify(classifiable_head, classifiable_base, diffs)
    all_findings = differential.findings + unclassified

    reasons: list[str] = []
    if head_result.overall_status == "failed":
        status, code = "failed", "analysis_failed"
        reasons.append("head_analysis_failed")
    else:
        status, code = "completed", None
        if not head_result.analysis_complete:
            status, code = "partial", "analysis_incomplete"
            reasons.extend(f"head:{r}" for r in head_result.incomplete_reasons)
        if base_ok_sources != {"ESLINT", "SEMGREP"} or base_result.overall_status != "completed":
            status, code = "partial", "differential_incomplete"
            reasons.append(f"base_analysis_{base_result.overall_status}")
        if base_unavailable_paths:
            status, code = "partial", "differential_incomplete"
            reasons.append("base_content_unavailable")
        snapshot_incomplete = [
            e for e in snapshot.skipped if e["reason"] not in ("not_analyzable_type",)
        ]
        if snapshot_incomplete:
            status, code = "partial", code or "analysis_incomplete"
            reasons.append("snapshot_skipped_files")

    error_message = "; ".join(
        m for m in (head_result.error_summary, base_result.error_summary) if m
    ) or None
    if status == "partial" and not error_message:
        error_message = "incomplete: " + ", ".join(sorted(set(reasons)))

    skipped_by_reason: dict[str, int] = {}
    for entry in snapshot.skipped:
        skipped_by_reason[entry["reason"]] = skipped_by_reason.get(entry["reason"], 0) + 1

    meta: dict[str, Any] = {
        "snapshot": {
            "head_sha": snapshot.head_sha,
            "base_sha": snapshot.base_sha,
            "merge_base_sha": snapshot.merge_base_sha,
            "changed_files_total": snapshot.changed_files_total,
            "files_selected": len(snapshot.files),
            "skipped_by_reason": skipped_by_reason,
        },
        "head": head_result.meta(),
        "base": base_result.meta(),
        "differential": {
            "new": differential.new_count,
            "existing": differential.existing_count,
            "moved": differential.moved_count,
            "fixed": differential.fixed_count,
            "unclassified": len(unclassified),
            "diff_sources": _count_by(diffs.values(), lambda d: d.source),
        },
        "incomplete_reasons": sorted(set(reasons)),
    }
    return AnalysisOutcome(status, all_findings, meta, code, redact_secrets(error_message))


def _count_by(items, key) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        k = key(item)
        out[k] = out.get(k, 0) + 1
    return out
