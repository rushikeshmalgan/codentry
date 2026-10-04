"""Regenerate the precomputed security-test report shown on the demo's
Security page (apps/web/public/security-report.json).

This runs the REAL security proof-of-concept suite once, offline, and writes
its real pass/fail/skip result to a static file the frontend reads. The demo
UI never executes pytest itself — that would mean exposing arbitrary command
execution from a browser, which is not something this project does. Re-run
this script after touching tests/test_security_poc.py or
tests/test_scope_guards.py so the committed report stays truthful.

Usage (from services/ai-review):
    .venv/Scripts/python.exe scripts/generate_security_report.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_ROOT.parent.parent
JUNIT_XML = SERVICE_ROOT / "scripts" / "_security_report.tmp.xml"
OUT_PATH = REPO_ROOT / "apps" / "web" / "public" / "security-report.json"

TEST_FILES = ["tests/test_security_poc.py", "tests/test_scope_guards.py"]


def _label(classname: str, name: str) -> str:
    short = name.removeprefix("test_poc_").removeprefix("test_")
    base = short.split("[")[0].replace("_", " ")
    base = base[0].upper() + base[1:]
    param = ""
    if "[" in name:
        param = " (" + name[name.index("[") + 1 : -1] + ")"
    suite = "security_poc" if "test_security_poc" in classname else "scope_guards"
    return base + param, suite


def main() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *TEST_FILES,
            "-q",
            "--tb=no",
            f"--junitxml={JUNIT_XML}",
        ],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
    )
    print(proc.stdout[-2000:])
    if proc.returncode not in (0, 1):
        # 1 = pytest ran but a test failed; anything else is a real execution error.
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"pytest invocation failed (exit {proc.returncode})")

    tree = ET.parse(JUNIT_XML)
    suite = tree.getroot().find("testsuite")

    scenarios = []
    for case in suite.findall("testcase"):
        label, group = _label(case.get("classname"), case.get("name"))
        skipped = case.find("skipped")
        failed = case.find("failure") or case.find("error")
        if failed is not None:
            status = "failed"
        elif skipped is not None:
            status = "skipped"
        else:
            status = "passed"
        scenarios.append(
            {
                "name": case.get("name"),
                "label": label,
                "group": group,
                "status": status,
                "duration_seconds": round(float(case.get("time", 0)), 3),
                "skip_reason": skipped.get("message") if skipped is not None else None,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "tests/test_security_poc.py + tests/test_scope_guards.py (run via scripts/generate_security_report.py)",
        "counts": {
            "total": int(suite.get("tests")),
            "passed": int(suite.get("tests")) - int(suite.get("failures")) - int(suite.get("errors")) - int(suite.get("skipped")),
            "failed": int(suite.get("failures")) + int(suite.get("errors")),
            "skipped": int(suite.get("skipped")),
        },
        "duration_seconds": round(float(suite.get("time", 0)), 2),
        "scenarios": scenarios,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    JUNIT_XML.unlink(missing_ok=True)
    print(f"wrote {OUT_PATH} ({report['counts']})")


if __name__ == "__main__":
    main()
