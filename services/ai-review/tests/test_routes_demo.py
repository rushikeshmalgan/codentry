"""The demo router runs the real analysis engine, and only exists in dev/test."""

import os
import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).parent.parent


def test_demo_fixtures_returns_the_real_fixture_source(client):
    resp = client.get("/demo/fixtures")
    assert resp.status_code == 200
    body = resp.json()
    ids = {f["id"] for f in body["fixtures"]}
    assert ids == {"eslint_sample", "semgrep_sample", "clean_sample"}
    for fixture in body["fixtures"]:
        assert fixture["source"]  # real file content, never empty


def test_demo_analyze_clean_fixture_has_no_findings(client):
    resp = client.get("/demo/analyze", params={"fixture": "clean"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert body["files"][0]["filename"] == "clean_sample.js"


def test_demo_analyze_eslint_fixture_returns_eslint_findings(client):
    resp = client.get("/demo/analyze", params={"fixture": "eslint"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["finding_count"] > 0
    assert all(f["source"] == "ESLINT" for f in body["findings"])


def test_demo_analyze_semgrep_fixture_returns_semgrep_findings(client):
    resp = client.get("/demo/analyze", params={"fixture": "semgrep"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["finding_count"] > 0
    assert all(f["source"] == "SEMGREP" for f in body["findings"])


def test_demo_analyze_all_combines_every_fixture(client):
    resp = client.get("/demo/analyze", params={"fixture": "all"})
    assert resp.status_code == 200
    body = resp.json()
    assert {f["filename"] for f in body["files"]} == {
        "eslint_sample.js",
        "semgrep_sample.js",
        "clean_sample.js",
    }
    sources = {f["source"] for f in body["findings"]}
    assert sources == {"ESLINT", "SEMGREP"}


def test_demo_analyze_rejects_an_unknown_fixture(client):
    resp = client.get("/demo/analyze", params={"fixture": "nope"})
    assert resp.status_code in (400, 422)


def _run_python(code: str, **env) -> str:
    full_env = {**os.environ, **env}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SERVICE_ROOT, capture_output=True, text=True, timeout=60, env=full_env,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


_ROUTE_CHECK = (
    "import app.main as m; "
    "print(any(p.startswith('/demo') for p in m.app.openapi()['paths']))"
)


def test_demo_router_is_absent_in_production():
    out = _run_python(
        _ROUTE_CHECK,
        ENVIRONMENT="production",
        CODENTRY_INTERNAL_WEBHOOK_SECRET="x",
        SUPABASE_URL="https://x.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="k",
    )
    assert out == "False"


def test_demo_router_is_present_in_development():
    out = _run_python(_ROUTE_CHECK, ENVIRONMENT="development")
    assert out == "True"
