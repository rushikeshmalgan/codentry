"""scripts/track_g_check.py: the Track G checklist, against a scripted fake of
Render, Vercel and Supabase's Data API. No network."""

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "track_g_check.py"
_spec = importlib.util.spec_from_file_location("track_g_check", _SCRIPT)
tg = importlib.util.module_from_spec(_spec)
sys.modules["track_g_check"] = tg
_spec.loader.exec_module(tg)

SUPABASE = "https://proj.supabase.example"
RENDER = "https://ai-review.render.example"
VERCEL = "https://codentry.vercel.example"
SERVICE_KEY = "service-role-key-must-never-be-printed"
ANON_KEY = "anon-key-must-never-be-printed"
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
HEAD = "a" * 40


def _ok(body, seconds=0.2, status=200):
    return tg.Response(status, json.dumps(body).encode(), seconds)


class FakeWorld:
    """Answers GET requests the way the real services would, from editable state."""

    def __init__(self):
        self.calls = []
        self.health = _ok({"status": "ok", "worker": "running"})
        self.status = _ok({"web": "ok", "backend": "ok"})
        self.webhook_route = tg.Response(405, b"", 0.1)
        self.anon_status = 401
        self.repos = [{"id": "repo-1", "is_active": True}]
        self.prs = [{"id": "pr-1", "head_sha": HEAD, "state": "open"}]
        self.runs = [
            {"id": "run-1", "status": "completed", "head_sha": HEAD, "merge_base_sha": "m" * 40,
             "attempts": 1, "error_code": None, "error_message": None,
             "analysis_meta": {"incomplete_reasons": []}, "delivery_id": "d-1",
             "created_at": "2026-11-18T11:58:00Z"},
        ]
        self.findings = [{"change_status": "new"}, {"change_status": "existing"}]
        self.deliveries = [
            {"delivery_id": "d-1", "status": "succeeded", "attempts": 1,
             "updated_at": "2026-11-18T11:58:00Z"},
        ]

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        parsed = urlparse(url)
        if url == f"{RENDER}/health":
            return self.health
        if url == f"{VERCEL}/api/status":
            return self.status
        if url == f"{VERCEL}/api/github/webhook":
            return self.webhook_route
        assert parsed.path.startswith("/rest/v1/"), url
        table = parsed.path.rsplit("/", 1)[-1]
        query = parse_qs(parsed.query)
        if headers["apikey"] == ANON_KEY:
            return tg.Response(self.anon_status, b"[]", 0.1)
        assert headers["apikey"] == SERVICE_KEY
        if table == "webhook_deliveries" and "delivery_id" in query:
            wanted = query["delivery_id"][0].removeprefix("eq.")
            return _ok([d for d in self.deliveries if d["delivery_id"] == wanted])
        return _ok({
            "repositories": self.repos,
            "pull_requests": self.prs,
            "review_runs": self.runs,
            "findings": self.findings,
            "webhook_deliveries": self.deliveries,
        }[table])


@pytest.fixture()
def world():
    return FakeWorld()


def _checker(world, **overrides):
    values = dict(supabase_url=SUPABASE, service_key=SERVICE_KEY, anon_key=ANON_KEY,
                  render_url=RENDER, vercel_url=VERCEL, now=lambda: NOW)
    values.update(overrides)
    return tg.TrackG(world, **values)


def _args(*extra):
    return tg.parse_args(["--repo", "octo-team/codentry-test", "--pr", "1", *extra])


def _by_name(checks):
    return {c.name: c for c in checks}


def test_a_healthy_run_passes_every_check(world):
    checks = tg.run_checks(_checker(world), _args())
    assert [c.name for c in checks if c.status != tg.PASS] == []
    assert _by_name(checks)["findings"].observed == "existing=1, new=1"


def test_the_checklist_only_reads(world):
    """Every request is a GET to a known service; nothing is ever written."""
    tg.run_checks(_checker(world), _args("--after-redelivery", "d-1"))
    hosts = {urlparse(url).netloc for url, _ in world.calls}
    assert hosts <= {urlparse(u).netloc for u in (SUPABASE, RENDER, VERCEL)}
    # http_get is the only transport and it hard-codes method="GET".
    assert 'method="GET"' in _SCRIPT.read_text(encoding="utf-8")


def test_secrets_never_appear_in_the_text_or_markdown_report(world, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON_KEY)
    report = tmp_path / "log.md"
    code = tg.main(["--repo", "o/r", "--pr", "1", "--render-url", RENDER,
                    "--vercel-url", VERCEL, "--markdown", str(report)], fetch=world)
    printed = capsys.readouterr().out + report.read_text(encoding="utf-8")
    assert code == 0
    assert SERVICE_KEY not in printed and ANON_KEY not in printed


@pytest.mark.parametrize(
    "seconds, verdict",
    [(3.0, "within the Vercel forward budget"),
     (9.0, "over the Vercel forward budget"),
     (31.0, "over GitHub's 10 s webhook timeout")],
)
def test_cold_start_is_measured_and_judged_against_both_budgets(world, seconds, verdict):
    world.health = _ok({"status": "ok", "worker": "running"}, seconds=seconds)
    check = _by_name(_checker(world).render_checks(cold_start=True))["render_cold_start"]
    assert check.status == tg.INFO and verdict in check.observed
    assert f"{seconds:.1f} s" in check.observed


def test_a_stopped_worker_fails_even_though_health_is_ok(world):
    world.health = _ok({"status": "ok", "worker": "not_running"})
    assert _by_name(_checker(world).render_checks(False))["render_worker"].status == tg.FAIL


def test_an_unreachable_render_fails_health(world):
    world.health = tg.Response(0, b"ConnectionRefusedError", 0.0)
    checks = _by_name(_checker(world).render_checks(False))
    assert checks["render_health"].status == tg.FAIL and "render_worker" not in checks


def test_vercel_reporting_the_backend_unreachable_fails(world):
    world.status = _ok({"web": "ok", "backend": "unreachable"}, status=503)
    assert _by_name(_checker(world).vercel_checks())["vercel_status"].status == tg.FAIL


def test_a_second_review_run_for_the_same_head_fails_the_dedup_check(world):
    world.runs.append(dict(world.runs[0], id="run-2"))
    checks = _by_name(tg.run_checks(_checker(world), _args()))
    assert checks["one_review_run_per_head"].status == tg.FAIL


def test_an_unfinished_run_is_info_not_a_failure(world):
    world.runs[0]["status"] = "running"
    checks = _by_name(tg.run_checks(_checker(world), _args()))
    assert checks["review_run_status"].status == tg.INFO
    assert "findings" not in checks  # nothing to count yet


def test_a_partial_run_passes_but_reports_its_reasons(world):
    world.runs[0].update(status="partial",
                         analysis_meta={"incomplete_reasons": ["head:semgrep:timeout"]})
    check = _by_name(tg.run_checks(_checker(world), _args()))["review_run_status"]
    assert check.status == tg.PASS and "head:semgrep:timeout" in check.observed


def test_a_failed_run_fails_and_shows_why(world):
    world.runs[0].update(status="failed", error_code="auth", error_message="401 from GitHub")
    check = _by_name(tg.run_checks(_checker(world), _args()))["review_run_status"]
    assert check.status == tg.FAIL and "auth" in check.observed


def test_a_delivery_stuck_in_processing_beyond_the_lease_fails(world):
    stale = (NOW - timedelta(seconds=tg.DELIVERY_LEASE_S + 60)).isoformat()
    world.deliveries.insert(0, {"delivery_id": "d-2", "status": "processing", "attempts": 1,
                                "updated_at": stale})
    check = _by_name(tg.run_checks(_checker(world), _args()))["webhook_deliveries"]
    assert check.status == tg.FAIL and "stuck-processing" in check.observed


def test_redelivery_passes_only_with_one_run_for_the_head(world):
    ok = _by_name(tg.run_checks(_checker(world), _args("--after-redelivery", "d-1")))
    assert ok["redelivery_dedup"].status == tg.PASS
    world.runs.append(dict(world.runs[0], id="run-2"))
    bad = _by_name(tg.run_checks(_checker(world), _args("--after-redelivery", "d-1")))
    assert bad["redelivery_dedup"].status == tg.FAIL


def test_an_open_anon_data_api_fails_the_exposure_check(world):
    world.anon_status = 200
    check = _by_name(tg.run_checks(_checker(world), _args()))["anon_data_api_closed"]
    assert check.status == tg.FAIL


def test_missing_configuration_skips_instead_of_guessing(world):
    checker = _checker(world, supabase_url=None, service_key=None, anon_key=None,
                       render_url=None, vercel_url=None)
    checks = tg.run_checks(checker, _args())
    assert {c.status for c in checks} == {tg.SKIP}
    assert world.calls == []


def test_exit_status_is_one_when_any_check_fails(world, monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    world.prs.clear()
    assert tg.main(["--repo", "o/r", "--pr", "1"], fetch=world) == 1
    assert "pull_request_row" in capsys.readouterr().out
