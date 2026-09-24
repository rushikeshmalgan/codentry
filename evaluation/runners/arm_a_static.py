"""Arm A — deterministic static analysis, differential (new findings only).

This is the arm Codentry ships today: ESLint with Codentry's baseline config
plus Codentry's six-rule Semgrep ruleset, run on the base and the head of a
change with identical tools, then classified new / existing / fixed.

It runs the *production* function (`analysis.snapshot_analysis`), not a copy,
so the harness measures what the worker actually does. The only thing this
module adds is turning a case on disk into the snapshot object the function
expects.

Labeling rule (docs/research-design.md): this arm is "ESLint + Codentry
baseline ruleset (6 rules) run with Semgrep {version}" — never "Semgrep's
performance".

Reporting policy: only findings with `change_status == "new"` count as
reported by the arm. `existing`/`fixed` findings are recorded for analysis but
are not the change's fault, and unclassifiable findings (change_status None)
are never treated as new — the same rule the production pipeline follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from analysis.changed_files import ChangedFile, PullRequestSnapshot
from analysis.finding import Finding
from analysis.snapshot_analysis import analyze_pull_request_snapshot
from analysis.workspace import SourceFile
from evaluation.case import CaseInputs

ARM_ID = "A"
REPORTED_POLICY = "change_status == 'new'"


@dataclass
class ArmAResult:
    status: str  # completed | partial | failed
    error_code: str | None
    findings: list[Finding]  # every classified finding (new/existing/fixed/unclassified)
    analysis_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def reported(self) -> list[Finding]:
        return [f for f in self.findings if f.change_status == "new"]


def arm_label(semgrep_version: str | None) -> str:
    return f"ESLint + Codentry baseline ruleset (6 rules) run with Semgrep {semgrep_version}"


def build_snapshot(inputs: CaseInputs) -> PullRequestSnapshot:
    files: list[ChangedFile] = []
    for f in inputs.files:
        base_path = f.previous_path or f.path
        files.append(
            ChangedFile(
                path=f.path,
                status=f.status,
                previous_path=f.previous_path,
                patch=None,  # no GitHub patch offline: the local difflib fallback is used
                head=SourceFile(f.path, f.head_content) if f.head_content is not None else None,
                base=SourceFile(base_path, f.base_content) if f.base_content is not None else None,
            )
        )
    return PullRequestSnapshot(
        repo_full_name=f"evaluation/{inputs.id}",
        pr_number=0,
        head_sha=inputs.head_sha,
        base_sha=inputs.base_sha,
        merge_base_sha=inputs.base_sha,
        files=files,
        changed_files_total=len(files),
        trusted_config_text=None,  # baseline config only: the arm is defined by Codentry's rules
    )


def run_arm_a(inputs: CaseInputs) -> ArmAResult:
    snapshot = build_snapshot(inputs)
    outcome = analyze_pull_request_snapshot(snapshot, scope=f"case:{inputs.id}")
    findings = sorted(
        outcome.findings,
        key=lambda f: (
            f.file_path, f.start_line, f.end_line, f.source, f.title, f.dedup_hash,
            f.change_status or "",
        ),
    )
    return ArmAResult(outcome.status, outcome.error_code, findings, outcome.meta)
