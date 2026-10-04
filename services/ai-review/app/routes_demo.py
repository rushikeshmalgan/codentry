"""Local demo endpoints: run the REAL analysis engine on the REAL fixtures.

This router exists only for the project demo/walkthrough. It calls
`analysis.run_static_analysis` — the exact function the review pipeline uses —
against the checked-in files in `analysis/fixtures/`, and returns the real
`Finding` objects. Nothing here is a mock, and nothing here accepts arbitrary
user-supplied code: the fixture set is fixed, read from disk, never from the
request body.

**Registered only in development/test** (see `app/main.py`): `Settings.is_loose_environment`
gates inclusion, the same switch that gates the FastAPI docs and the in-memory
store fallback. A production deployment never has this router at all — there
is no secret to misconfigure, no flag to forget; the route simply does not
exist. No GitHub call, no database write, no mutation of any kind — every
endpoint here is a GET.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException

from analysis.static_analysis import run_static_analysis

router = APIRouter(prefix="/demo", tags=["demo"])

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "analysis" / "fixtures"

FixtureId = Literal["all", "eslint", "semgrep", "clean"]

_FIXTURE_FILES: dict[str, list[str]] = {
    "all": ["eslint_sample.js", "semgrep_sample.js", "clean_sample.js"],
    "eslint": ["eslint_sample.js"],
    "semgrep": ["semgrep_sample.js"],
    "clean": ["clean_sample.js"],
}
_FIXTURE_LABELS: dict[str, str] = {
    "eslint_sample.js": "ESLint Sample",
    "semgrep_sample.js": "Semgrep Sample",
    "clean_sample.js": "Clean Sample",
}


@router.get("/fixtures")
async def list_fixtures() -> dict:
    """The selectable fixtures, with their real source text (for the code viewer)."""
    return {
        "fixtures": [
            {
                "id": name.removesuffix(".js"),
                "filename": name,
                "label": _FIXTURE_LABELS[name],
                "source": (FIXTURES_DIR / name).read_text(encoding="utf-8"),
            }
            for name in _FIXTURE_FILES["all"]
        ]
    }


@router.get("/analyze")
async def analyze(fixture: FixtureId = "all") -> dict:
    """Run the real ESLint + Semgrep pipeline on the selected fixture(s)."""
    filenames = _FIXTURE_FILES.get(fixture)
    if filenames is None:
        raise HTTPException(status_code=400, detail=f"unknown fixture {fixture!r}")

    started = time.perf_counter()
    result = run_static_analysis(str(FIXTURES_DIR), filenames)
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    sources = {name: (FIXTURES_DIR / name).read_text(encoding="utf-8") for name in filenames}
    findings = [f.model_dump(mode="json") for f in result.findings]
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (severity_order.get(f["severity"], 9), f["file_path"], f["start_line"]))

    return {
        "fixture": fixture,
        "files": [{"filename": name, "source": sources[name]} for name in filenames],
        "elapsed_ms": elapsed_ms,
        "overall_status": result.overall_status,
        "eslint_status": result.eslint_status,
        "semgrep_status": result.semgrep_status,
        "eslint_error": result.eslint_error,
        "semgrep_error": result.semgrep_error,
        "finding_count": len(findings),
        "severity_counts": {
            s: sum(1 for f in findings if f["severity"] == s)
            for s in ("critical", "high", "medium", "low", "info")
        },
        "findings": findings,
    }
